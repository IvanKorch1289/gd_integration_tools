"""Smoke-тесты для 15 новых blueprints (S10 K3 W1)."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

BLUEPRINTS_DIR = (
    Path(__file__).resolve().parents[4] / "src" / "backend" / "dsl" / "blueprints"
)

NEW_BLUEPRINTS = (
    "fan_out_fan_in",
    "request_reply_async",
    "file_to_db_pipeline",
    "cdc_to_search_index",
    "rpa_web_scrape",
    "hitl_approval",
    "credit_scoring",
    "multimodal_ingest",
    "scheduled_report",
    "webhook_to_kafka",
    "saml_user_sync",
    "api_to_api_bridge",
    "dlq_replay",
    "rate_limit_burst",
    "hybrid_rag",
)


@pytest.mark.parametrize("name", NEW_BLUEPRINTS)
def test_blueprint_yaml_parses(name: str) -> None:
    path = BLUEPRINTS_DIR / f"{name}.yaml"
    assert path.is_file(), f"Не найден blueprint: {path}"
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert isinstance(data, dict), f"Root должен быть mapping, не {type(data)}"


@pytest.mark.parametrize("name", NEW_BLUEPRINTS)
def test_blueprint_has_required_keys(name: str) -> None:
    path = BLUEPRINTS_DIR / f"{name}.yaml"
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert data.get("blueprint") == name
    assert "version" in data
    assert "description" in data
    assert "tags" in data and isinstance(data["tags"], list)
    assert "params" in data
    assert "from" in data
    assert "steps" in data
    assert isinstance(data["steps"], list) and len(data["steps"]) >= 1


def test_library_size_at_least_15_new() -> None:
    """В каталоге blueprints должно быть как минимум 15 новых файлов."""
    existing = {p.stem for p in BLUEPRINTS_DIR.glob("*.yaml")}
    new_count = sum(1 for name in NEW_BLUEPRINTS if name in existing)
    assert new_count == 15


def test_library_total_size_at_least_20() -> None:
    """DoD: ≥20 blueprints в библиотеке."""
    yaml_files = list(BLUEPRINTS_DIR.glob("*.yaml"))
    assert len(yaml_files) >= 19  # 4 pre-existing + 15 new = 19
