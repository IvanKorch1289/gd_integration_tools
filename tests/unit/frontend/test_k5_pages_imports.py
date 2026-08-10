"""Smoke-тесты импорта Streamlit-страниц Sprint 7 Team K5.

Проверяют AST-syntax новых страниц и базовые архитектурные инварианты
(только через api_client / capability-checked facades; нет прямого импорта
``src.backend.infrastructure`` в frontend-слое).
"""

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
    "54_Replay_DLQ.py",
    "57_Файлы_S3.py",
    "70_Тенанты.py",
    "71_Матрица_возможностей.py",
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
    """DLQ Replay (S173 refactor) — shim делегирует в _groups/replay/render.

    Реальная логика вынесена в ``render_dlq_replay()``; проверяем shim +
    OutboxBackend usage в render.py.
    """
    src = _page_path("54_Replay_DLQ.py").read_text(encoding="utf-8")
    assert "render_dlq_replay" in src
    render_path = Path(__file__).resolve().parents[3] / (
        "src/frontend/streamlit_app/pages/_groups/replay/render.py"
    )
    if not render_path.exists():
        pytest.skip(f"render.py not found at {render_path}")
    render_src = render_path.read_text(encoding="utf-8")
    assert "OutboxBackend" in render_src or "src.backend.core.messaging" in render_src


def test_dlq_replay_has_bulk_and_manual_modes() -> None:
    """DLQ Replay (S173 refactor) — UI logic в render.py."""
    render_path = Path(__file__).resolve().parents[3] / (
        "src/frontend/streamlit_app/pages/_groups/replay/render.py"
    )
    if not render_path.exists():
        pytest.skip(f"render.py not found at {render_path}")
    render_src = render_path.read_text(encoding="utf-8")
    assert "multiselect" in render_src or "selectbox" in render_src
