# ruff: noqa: S101
"""Sprint 14 K5 W1 — unit-тесты ``MigrationDiffer`` + render_guide."""

from __future__ import annotations

import sys
from pathlib import Path

_TOOLS = Path(__file__).resolve().parents[3] / "tools"
if str(_TOOLS) not in sys.path:
    sys.path.insert(0, str(_TOOLS))

import plugin_migration_diff as pmd  # noqa: E402


def _toml_old() -> dict:
    return {
        "name": "credit_pipeline",
        "version": "1.0.0",
        "requires_core": ">=0.2,<0.3",
        "entry_class": "extensions.credit_pipeline.plugin.Plugin",
        "capabilities": [
            {"name": "db.read", "scope": "credit_db"},
            {"name": "secrets.read", "scope": "vault://credit/*"},
        ],
        "provides": {
            "actions": ["credit.score"],
            "processors": ["bki_normalizer"],
        },
        "compatibility": {"requires_plugins": {"shared_models": ">=1.0,<2.0"}},
    }


def _toml_new() -> dict:
    return {
        "name": "credit_pipeline",
        "version": "2.0.0",
        "requires_core": ">=0.2,<0.4",
        "entry_class": "extensions.credit_pipeline.plugin.Plugin",
        "capabilities": [
            {"name": "db.read", "scope": "credit_db_v2"},  # scope изменился
            {"name": "ai.llm.openai"},  # added
        ],
        "provides": {
            "actions": ["credit.score", "credit.assess"],  # +credit.assess
            # processors удалены полностью → breaking
        },
        "compatibility": {
            "requires_plugins": {"shared_models": ">=2.0,<3.0"}  # spec изменён
        },
    }


def test_diff_capabilities_added_removed_changed() -> None:
    diff = pmd.MigrationDiffer().diff("credit_pipeline", _toml_old(), _toml_new())
    caps = diff.payload["capabilities"]
    assert "ai.llm.openai" in caps["added"]
    assert "secrets.read" in caps["removed"]
    assert any(c["name"] == "db.read" for c in caps["scope_changed"])


def test_diff_provides_added_and_removed() -> None:
    diff = pmd.MigrationDiffer().diff("credit_pipeline", _toml_old(), _toml_new())
    assert diff.payload["provides_added"].get("actions") == ["credit.assess"]
    assert diff.payload["provides_removed"].get("processors") == ["bki_normalizer"]


def test_breaking_changes_collected() -> None:
    diff = pmd.MigrationDiffer().diff("credit_pipeline", _toml_old(), _toml_new())
    kinds = {b["kind"] for b in diff.payload["breaking_changes"]}
    assert "capability removed" in kinds  # secrets.read удалён
    assert "processors removed" in kinds  # bki_normalizer удалён
    assert "dependency spec changed" in kinds


def test_summary_counters() -> None:
    diff = pmd.MigrationDiffer().diff("credit_pipeline", _toml_old(), _toml_new())
    s = diff.payload["summary"]
    assert s["capabilities_added"] == 1
    assert s["capabilities_removed"] == 1
    assert s["provides_added"] == 1
    assert s["provides_removed"] == 1
    assert s["requires_changed"] == 1
    assert s["core_changed"] == 1


def test_render_guide_returns_markdown(tmp_path: Path) -> None:
    diff = pmd.MigrationDiffer().diff("credit_pipeline", _toml_old(), _toml_new())
    md = pmd.render_guide(diff)
    assert "Migration guide: credit_pipeline 1.0.0 → 2.0.0" in md
    assert "Breaking changes" in md
    assert "bki_normalizer" in md


def test_no_diff_when_identical() -> None:
    same = _toml_old()
    diff = pmd.MigrationDiffer().diff("credit_pipeline", same, same)
    s = diff.payload["summary"]
    assert s["capabilities_added"] == 0
    assert s["capabilities_removed"] == 0
    assert s["provides_added"] == 0
    assert s["provides_removed"] == 0
    assert s["core_changed"] == 0
    assert diff.payload["has_breaking"] is False
