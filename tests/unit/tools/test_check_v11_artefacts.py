# ruff: noqa: S101
"""Тесты tools/check_v11_artefacts.py — pre-push gate свежести V11-артефактов."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_TOOLS = Path(__file__).resolve().parents[3] / "tools"
sys.path.insert(0, str(_TOOLS))

import check_v11_artefacts as check_mod  # noqa: E402
import export_v11_artefacts as export_mod  # noqa: E402


def test_passes_when_artefacts_fresh(capsys: pytest.CaptureFixture[str]) -> None:
    """Если committed-файлы соответствуют коду — exit 0 и три ``[OK]``-строки."""
    # Сначала освежаем committed-артефакты, чтобы тест был детерминирован
    # независимо от состояния рабочего дерева.
    assert export_mod.main(["all"]) == 0
    rc = check_mod.main()
    captured = capsys.readouterr().out
    assert rc == 0
    assert captured.count("[OK]") == 3
    assert "[FAIL]" not in captured


def test_fails_when_committed_stale(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Подменяем committed-capabilities на устаревший слепок — exit 1."""
    stale = tmp_path / "stale.md"
    stale.write_text("# stale capability catalog\n", encoding="utf-8")
    monkeypatch.setattr(check_mod, "CAPABILITIES_MD", stale)
    rc = check_mod.main()
    captured = capsys.readouterr().out
    assert rc == 1
    assert "[FAIL]" in captured
    assert "stale" in captured
    assert "make v11-artefacts" in captured


def test_fails_when_artefact_missing(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    """Если committed-файла нет — exit 1 с понятным сообщением."""
    monkeypatch.setattr(check_mod, "PLUGIN_SCHEMA", tmp_path / "does_not_exist.json")
    rc = check_mod.main()
    captured = capsys.readouterr().out
    assert rc == 1
    assert "[FAIL]" in captured
    assert "does_not_exist.json" in captured


def test_main_returns_zero_on_clean_repo(capsys: pytest.CaptureFixture[str]) -> None:
    """Smoke-тест: прямой вызов ``main()`` после регенерации даёт exit 0."""
    assert export_mod.main(["all"]) == 0
    rc = check_mod.main()
    captured = capsys.readouterr().out
    assert rc == 0
    # Все три committed-артефакта проверены.
    assert "plugin.toml.schema.json" in captured
    assert "route.toml.schema.json" in captured
    assert "capabilities.md" in captured
