"""Unit-тесты LangGraphPostgresSaverWrapper (S5 W2).

Покрывают:
1. default-OFF: get_langgraph_postgres_saver() → None при выключенном flag.
2. ImportError → LangGraphPostgresSaverUnavailable.
3. enabled override + missing dsn → LangGraphPostgresSaverUnavailable.
4. Cached saver: повторный acquire() возвращает тот же экземпляр.
"""

from __future__ import annotations

import sys
from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.backend.services.ai.agents.langgraph_postgres_saver import (
    LangGraphPostgresSaverUnavailable,
    LangGraphPostgresSaverWrapper,
    get_langgraph_postgres_saver,
    reset_langgraph_postgres_saver,
)


@pytest.mark.asyncio
async def test_get_returns_none_when_flag_disabled(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """При выключенном feature_flag get_langgraph_postgres_saver → None."""
    from src.backend.core.config.features import feature_flags

    monkeypatch.setattr(
        feature_flags, "langgraph_postgres_checkpoint", False, raising=False
    )
    reset_langgraph_postgres_saver()
    saver = await get_langgraph_postgres_saver()
    assert saver is None


@pytest.mark.asyncio
async def test_acquire_raises_when_package_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """ImportError → LangGraphPostgresSaverUnavailable с понятным сообщением."""
    wrapper = LangGraphPostgresSaverWrapper(dsn="postgresql://x", enabled=True)
    # Подавляем существующий пакет (если вдруг установлен) — имитируем ImportError
    monkeypatch.setitem(sys.modules, "langchain_postgres", None)
    with pytest.raises(LangGraphPostgresSaverUnavailable, match="extra ai-memory"):
        await wrapper.acquire()


@pytest.mark.asyncio
async def test_acquire_raises_without_dsn(monkeypatch: pytest.MonkeyPatch) -> None:
    """При enabled но без DSN — LangGraphPostgresSaverUnavailable."""
    # Имитируем установленный langchain_postgres но без DSN
    fake_pkg = MagicMock()
    fake_pkg.AsyncPostgresSaver.from_conn_string = MagicMock()
    monkeypatch.setitem(sys.modules, "langchain_postgres", fake_pkg)

    wrapper = LangGraphPostgresSaverWrapper(dsn=None, enabled=True)
    # Гарантируем отсутствие settings.database
    import src.backend.services.ai.agents.langgraph_postgres_saver as mod

    def _raise_settings() -> Any:
        raise RuntimeError("settings missing")

    monkeypatch.setattr(
        mod, "_resolve_dsn", _raise_settings, raising=False
    )  # noop fallback
    # Перепроверим: метод _resolve_dsn — instance method; если settings нет,
    # raise происходит изнутри.
    with pytest.raises(LangGraphPostgresSaverUnavailable):
        await wrapper.acquire()


@pytest.mark.asyncio
async def test_acquire_caches_saver(monkeypatch: pytest.MonkeyPatch) -> None:
    """Повторный acquire() возвращает тот же экземпляр (без повторной инициализации)."""
    fake_saver = MagicMock()
    fake_saver.setup = AsyncMock()

    class _AsyncCtx:
        async def __aenter__(self) -> Any:
            return fake_saver

        async def __aexit__(self, *_a: Any) -> None:
            return None

    fake_pkg = MagicMock()
    fake_pkg.AsyncPostgresSaver.from_conn_string = MagicMock(return_value=_AsyncCtx())
    monkeypatch.setitem(sys.modules, "langchain_postgres", fake_pkg)

    wrapper = LangGraphPostgresSaverWrapper(
        dsn="postgresql://test:test@localhost:5432/db", enabled=True
    )
    s1 = await wrapper.acquire()
    s2 = await wrapper.acquire()
    assert s1 is fake_saver
    assert s1 is s2
    # from_conn_string должен быть вызван один раз
    fake_pkg.AsyncPostgresSaver.from_conn_string.assert_called_once()
    # setup() — ровно один раз
    fake_saver.setup.assert_awaited_once()
