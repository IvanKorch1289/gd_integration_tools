"""Regression tests для check_feature_flag_dependencies.py (cycle 158+ fixes).

Per v4 §10 P1 'evidence требует testable surface': 2 commits (`fccf8b2aa`
+ `12a68b878`) исправили broken gate:

Fix #1 (fccf8b2aa): validator.py → validator/ package layout.
- Pre-fix: gate падал с 'validator.py не найден' (file decomp поменял layout,
  никто не обновил gate).
- Post-fix: _load_validator_source() handles оба layouts (legacy + modern).

Fix #2 (12a68b878): regex robustness.
- Pre-fix-2: regex не ловил `_FEATURE_FLAG_DEPENDENCIES: Final[Mapping[...]] = {`
  (type annotation между name и '=' ломал pattern).
- Pre-fix-2: после Fix #1 grep видел только ПОСЛЕДНИЙ ключ dict
  (greedy '[^}]*' + '"([^"]+)":' — last match wins).
- Post-fix-2: _extract_dict_keys() brace-balanced scan + comment-aware.

Tests below покрывают все три regressive path.
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest


def _load_module():
    """Подгрузить tools/checks/check_feature_flag_dependencies.py через importlib."""
    path = (
        Path(__file__).resolve().parents[3]
        / "tools"
        / "checks"
        / "check_feature_flag_dependencies.py"
    )
    spec = importlib.util.spec_from_file_location("_cfd_test", path)
    if spec is None or spec.loader is None:
        raise ImportError("Не удалось загрузить check_feature_flag_dependencies.py")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


mod = _load_module()


def _patch_validator_paths(monkeypatch, pkg, path):
    """Helper: патчит _VALIDATOR_PKG и _VALIDATOR_PATH для тестов."""
    monkeypatch.setattr(mod, "_VALIDATOR_PKG", pkg)
    monkeypatch.setattr(mod, "_VALIDATOR_PATH", path)


# ──────────────────── Fix #1: validator.py → validator/ package ─────────────────


def test_load_validator_source_handles_legacy_single_file(
    tmp_path: Path, monkeypatch
) -> None:
    """Legacy single-file layout: validator.py (singular) → read content."""
    legacy_file = tmp_path / "validator.py"
    legacy_file.write_text(
        '_FEATURE_FLAG_DEPENDENCIES = {"foo": ("bar",)}\n', encoding="utf-8"
    )

    _patch_validator_paths(monkeypatch, tmp_path / "nonexistent_pkg", legacy_file)
    src = mod._load_validator_source()
    assert src is not None
    assert "_FEATURE_FLAG_DEPENDENCIES" in src
    assert src.count('"foo"') == 1


def test_load_validator_source_handles_modern_package(
    tmp_path: Path, monkeypatch
) -> None:
    """Modern package: validator/ with multiple .py → brace-balanced concat."""
    pkg = tmp_path / "validator_pkg"
    pkg.mkdir()
    init = pkg / "__init__.py"
    init.write_text(
        "_FEATURE_FLAG_DEPENDENCIES: Final[Mapping[str, tuple[str, ...]]] = {\n"
        '    "flag_a": ("base_a",),\n'
        "}\n",
        encoding="utf-8",
    )
    helpers = pkg / "_helpers.py"
    helpers.write_text(
        "_FEATURE_FLAG_DEPENDENCIES_STRICT_AUTOMAP: Final[frozenset[str]] = frozenset(\n"
        '    {"flag_b", "flag_c"},\n'
        ")\n",
        encoding="utf-8",
    )

    _patch_validator_paths(monkeypatch, pkg, tmp_path / "nonexistent_single_file.py")
    src = mod._load_validator_source()
    assert src is not None
    # __init__.py content included
    assert "flag_a" in src
    # _helpers.py content included
    assert "flag_b" in src
    assert "flag_c" in src


def test_load_validator_source_returns_none_when_nothing_exists(
    tmp_path: Path, monkeypatch
) -> None:
    """Если ни single-file ни package не существует → None."""
    _patch_validator_paths(
        monkeypatch, tmp_path / "nonexistent_pkg", tmp_path / "nonexistent_validator.py"
    )
    src = mod._load_validator_source()
    assert src is None


# ──────────────────── Fix #2: regex robustness ────────────────────────────────────


def test_parse_declared_handles_type_annotation_between_name_and_eq() -> None:
    """Pre-fix bug: regex `_FEATURE_FLAG_DEPENDENCIES\\s*=\\s*\\{` failed на:

    ``_FEATURE_FLAG_DEPENDENCIES: Final[Mapping[...]] = { ... }``

    потому что между name и ``=`` стоит ``: Final[Mapping[...]]``.

    Post-fix: regex допускает type annotation через `\\s*(?::[^=\n]+)?=\\s*`.
    """
    src = (
        "_FEATURE_FLAG_DEPENDENCIES: Final[Mapping[str, tuple[str, ...]]] = {\n"
        '    "supply_chain_strict_mode": ("supply_chain_finale_strict",)\n'
        "}\n"
    )
    warn, crit = mod._parse_declared_dependencies(src)
    assert "supply_chain_strict_mode" in warn
    assert "supply_chain_strict_mode" not in crit


def test_parse_declared_critical_handles_type_annotation() -> None:
    """Same fix для CRITICAL dict — was missing `lsp_server_strict`, etc."""
    src = (
        "_FEATURE_FLAG_DEPENDENCIES_CRITICAL: Final[Mapping[str, tuple[str, ...]]] = {\n"
        "    # Commented-out flag (должен быть skipped)\n"
        '    # "waf_strict_zero_allowlist": ("waf_outbound_via_facade",),\n'
        '    "lsp_server_strict": ("lsp_server",),\n'
        '    "outbound_metering_strict": ("metering_per_host",),\n'
        '    "ai_prompt_sweep_strict": ("ai_prompt_sweep",),\n'
        "}\n"
    )
    warn, crit = mod._parse_declared_dependencies(src)
    # Per-fix bugs: только LAST key был visible (ai_prompt_sweep_strict).
    # Post-fix: ВСЕ ключи extracted.
    assert "lsp_server_strict" in crit
    assert "outbound_metering_strict" in crit
    assert "ai_prompt_sweep_strict" in crit
    # Commented-out не считается declared.
    assert "waf_strict_zero_allowlist" not in crit


def test_parse_declared_ignores_commented_out_keys() -> None:
    """Lines starting с '#' должны быть skipped (comment-aware)."""
    src = (
        "_FEATURE_FLAG_DEPENDENCIES_CRITICAL = {\n"
        '    # "commented_out": ("x",),\n'
        '    "real_key": ("base",),\n'
        "}\n"
    )
    _, crit = mod._parse_declared_dependencies(src)
    assert "real_key" in crit
    assert "commented_out" not in crit


def test_parse_declared_extracts_automap_frozenset() -> None:
    """_FEATURE_FLAG_DEPENDENCIES_STRICT_AUTOMAP (frozenset) — должен работать
    вне зависимости от type annotation handling (отдельный regex path)."""
    src = (
        "_FEATURE_FLAG_DEPENDENCIES_STRICT_AUTOMAP: Final[frozenset[str]] = frozenset(\n"
        '    {"flag_x", "flag_y", "flag_z"},\n'
        ")\n"
    )
    warn, _ = mod._parse_declared_dependencies(src)
    assert "flag_x" in warn
    assert "flag_y" in warn
    assert "flag_z" in warn


def test_parse_declared_real_world_validator_helpers() -> None:
    """Integration: реальный _helpers.py в проекте должен парситься без ошибок."""
    helpers_path = (
        Path(__file__).resolve().parents[3]
        / "src/backend/core/config/validator/_helpers.py"
    )
    if not helpers_path.exists():
        pytest.skip(f"Validator helpers not found: {helpers_path}")
    src = helpers_path.read_text(encoding="utf-8")
    warn, crit = mod._parse_declared_dependencies(src)

    # Per реальный исходник (после fix #2):
    # - 3 CRITICAL entries: outbound_metering_strict, lsp_server_strict,
    #   ai_prompt_sweep_strict.
    assert "lsp_server_strict" in crit
    assert "outbound_metering_strict" in crit
    assert "ai_prompt_sweep_strict" in crit
    # AUTOMAP contributes many to warn:
    assert len(warn) > 5


# ──────────────────── Integration check: gate state на real source ────────────────


def test_run_check_returns_0_when_all_strict_flags_declared() -> None:
    """Если все *_strict flags declared → exit 0 (gate green)."""
    helpers_path = (
        Path(__file__).resolve().parents[3]
        / "src/backend/core/config/validator/_helpers.py"
    )
    if not helpers_path.exists():
        pytest.skip(f"Validator helpers not found: {helpers_path}")
    rc = mod.run_check(strict_mode=True)
    # Real state: 18 flags all declared post-fix → 0 in strict mode.
    assert rc == 0


def test_run_check_returns_1_when_undeclared_flags_present(monkeypatch) -> None:
    """If helper функции возвращают undeclared *_strict → exit 1 in strict mode."""
    # Подменяем _find_features_source чтобы возвращал тестовый строгий флаг.
    monkeypatch.setattr(
        mod,
        "_find_features_source",
        lambda: ({"orphan_strict": 99}, "orphan_strict: bool = Field(default=False)"),
    )

    # Source где у нас нет этого флага в declared.
    monkeypatch.setattr(
        mod, "_load_validator_source", lambda: "_FEATURE_FLAG_DEPENDENCIES = {}\n"
    )

    rc = mod.run_check(strict_mode=True)
    assert rc == 1
