"""Smoke-тесты импорта Streamlit-страниц Sprint 7 Team K5.

Проверяют AST-syntax новых страниц и базовые архитектурные инварианты
(только через api_client / capability-checked facades; нет прямого импорта
``src.backend.infrastructure`` в frontend-слое).
"""
# ruff: noqa: S101

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


def _page_path(filename: str) -> Path:
    """Вернуть абсолютный путь к Streamlit-странице."""
    return (
        Path(__file__).resolve().parents[3]
        / "src"
        / "frontend"
        / "streamlit_app"
        / "pages"
        / filename
    )


K5_PAGES = [
    "14_DLQ_Replay.py",
    "13_Resilience_Dashboard.py",
    "15_Pool_Monitor.py",
    "70_Tenants.py",
    "71_Capabilities.py",
    "30_Files_S3.py",
]


@pytest.mark.parametrize("filename", K5_PAGES)
def test_streamlit_page_is_valid_python(filename: str) -> None:
    """Страница парсится как валидный Python-модуль."""
    page = _page_path(filename)
    if not page.exists():
        pytest.skip(f"Страница не создана: {filename}")
    source = page.read_text(encoding="utf-8")
    compile(source, str(page), "exec")


@pytest.mark.parametrize("filename", K5_PAGES)
def test_streamlit_page_spec_loadable(filename: str) -> None:
    """``importlib.util.spec_from_file_location`` возвращает spec."""
    page = _page_path(filename)
    if not page.exists():
        pytest.skip(f"Страница не создана: {filename}")
    spec = importlib.util.spec_from_file_location(
        f"_k5_page_{filename.replace('.', '_')}", page
    )
    assert spec is not None, f"spec_from_file_location вернул None для {filename}"
    assert spec.loader is not None


@pytest.mark.parametrize("filename", K5_PAGES)
def test_frontend_layer_isolation(filename: str) -> None:
    """Frontend-слой не импортирует ``src.backend.infrastructure``.

    CLAUDE.md V15: frontend/streamlit_app/ → только публичный API +
    REST через api_client.py + core-Protocols + core/messaging (Fake).
    Прямой импорт infrastructure запрещён.
    """
    page = _page_path(filename)
    if not page.exists():
        pytest.skip(f"Страница не создана: {filename}")
    src = page.read_text(encoding="utf-8")
    assert "from src.backend.infrastructure" not in src, (
        f"{filename}: frontend не должен импортировать infrastructure напрямую"
    )


def test_dlq_replay_uses_outbox_protocol() -> None:
    """DLQ Replay использует core/messaging OutboxBackend (Protocol)."""
    src = _page_path("14_DLQ_Replay.py").read_text(encoding="utf-8")
    assert "from src.backend.core.messaging" in src
    assert "FakeOutbox" in src
    assert "dlq_unified_enabled" in src
    assert "override_payload" in src


def test_dlq_replay_has_bulk_and_manual_modes() -> None:
    """DLQ Replay предоставляет bulk + manual edit-and-replay."""
    src = _page_path("14_DLQ_Replay.py").read_text(encoding="utf-8")
    assert "multiselect" in src
    assert "text_area" in src
