"""LangGraph AsyncPostgresSaver wrapper (S5 W2).

Назначение:
    Тонкая обёртка над ``langchain_postgres.AsyncPostgresSaver`` с
    ленивым импортом, gracefully падающим при отсутствии extra
    ``ai-memory``. Используется для persistence LangGraph state в PG.

Активация:
    ``feature_flags.langgraph_postgres_checkpoint`` (default-OFF).
    При выключенном flag :func:`get_langgraph_postgres_saver` возвращает
    None — caller должен обработать это и fallback на in-memory checkpointer.

Использование::

    saver = await get_langgraph_postgres_saver()
    if saver is None:
        # langchain_postgres не установлен или flag выключен
        from langgraph.checkpoint.memory import MemorySaver
        saver = MemorySaver()

    graph = StateGraph(...).compile(checkpointer=saver)
"""

from __future__ import annotations

import logging
from typing import Any

__all__ = (
    "LangGraphPostgresSaverUnavailable",
    "LangGraphPostgresSaverWrapper",
    "get_langgraph_postgres_saver",
)

logger = logging.getLogger(__name__)


class LangGraphPostgresSaverUnavailable(RuntimeError):
    """langchain_postgres не установлен или feature-flag выключен."""


class LangGraphPostgresSaverWrapper:
    """Lazy-обёртка над AsyncPostgresSaver для checkpoint LangGraph state.

    При первом обращении пытается импортировать
    ``langchain_postgres.AsyncPostgresSaver`` и инициализировать его
    из переданного DSN. Все исключения импорта/коннекта оборачиваются в
    :class:`LangGraphPostgresSaverUnavailable` для явной обработки caller.

    Безопасно для повторных вызовов :meth:`acquire`: возвращает уже
    инициализированный экземпляр.

    Attributes:
        _dsn: PostgreSQL connection string.
        _saver: Кешированный AsyncPostgresSaver (после первой инициализации).
        _enabled: Snapshot feature_flag на момент создания.
    """

    def __init__(self, *, dsn: str | None = None, enabled: bool | None = None) -> None:
        """Инициализирует wrapper без попытки импорта (lazy).

        Args:
            dsn: PostgreSQL DSN (postgresql://user:pass@host:5432/db).
                Если None — берётся из settings.database.dsn.
            enabled: Override feature-flag (для тестов). При None —
                читается из feature_flags.langgraph_postgres_checkpoint.
        """
        self._dsn = dsn
        self._saver: Any = None
        self._enabled_override = enabled

    @property
    def enabled(self) -> bool:
        """True если feature_flag активен ИЛИ передан enabled=True в __init__."""
        if self._enabled_override is not None:
            return bool(self._enabled_override)
        try:
            from src.backend.core.config.features import feature_flags

            return bool(getattr(feature_flags, "langgraph_postgres_checkpoint", False))
        except Exception as _:  # noqa: BLE001
            return False

    def _resolve_dsn(self) -> str:
        """Возвращает DSN из конструктора либо из settings."""
        if self._dsn:
            return self._dsn
        try:
            from src.backend.core.config.application_settings import settings

            db = getattr(settings, "database", None)
            if db is not None:
                dsn = getattr(db, "dsn", None) or getattr(db, "url", None)
                if dsn:
                    return str(dsn)
        except Exception as _:  # noqa: BLE001
            pass
        raise LangGraphPostgresSaverUnavailable(
            "DSN для AsyncPostgresSaver не передан и не найден в settings.database"
        )

    async def acquire(self) -> Any:
        """Возвращает инициализированный AsyncPostgresSaver.

        Returns:
            Экземпляр ``langchain_postgres.AsyncPostgresSaver``.

        Raises:
            LangGraphPostgresSaverUnavailable: при отключённом flag, отсутствии
                extra ai-memory или ошибке инициализации.
        """
        if not self.enabled:
            raise LangGraphPostgresSaverUnavailable(
                "feature_flag.langgraph_postgres_checkpoint выключен"
            )
        if self._saver is not None:
            return self._saver
        try:
            from langchain_postgres import (
                AsyncPostgresSaver,  
            )
        except ImportError as exc:
            raise LangGraphPostgresSaverUnavailable(
                "Пакет langchain_postgres не установлен — добавьте extra ai-memory"
            ) from exc

        dsn = self._resolve_dsn()
        try:
            # AsyncPostgresSaver.from_conn_string возвращает async-context-manager;
            # для долгоживущего использования вызываем .__aenter__ вручную и
            # храним сам объект до явного close.
            ctx = AsyncPostgresSaver.from_conn_string(dsn)
            saver = await ctx.__aenter__()
        except Exception as exc:  # noqa: BLE001
            raise LangGraphPostgresSaverUnavailable(
                f"Не удалось инициализировать AsyncPostgresSaver: {exc}"
            ) from exc

        # setup() создаёт служебные таблицы checkpoint_*
        try:
            setup = getattr(saver, "setup", None)
            if setup is not None:
                await setup()
        except Exception as exc:  # noqa: BLE001
            logger.warning("AsyncPostgresSaver.setup() failed: %s", exc)

        self._saver = saver
        return saver

    async def close(self) -> None:
        """Закрывает соединение AsyncPostgresSaver если он был создан."""
        if self._saver is None:
            return
        try:
            close = getattr(self._saver, "close", None)
            if close is not None:
                result = close()
                if hasattr(result, "__await__"):
                    await result
        except Exception as exc:  # noqa: BLE001
            logger.debug("AsyncPostgresSaver.close() error: %s", exc)
        finally:
            self._saver = None


_wrapper: LangGraphPostgresSaverWrapper | None = None


def _factory() -> LangGraphPostgresSaverWrapper:
    """Создаёт singleton wrapper (без acquire — ленивая инициализация)."""
    global _wrapper
    if _wrapper is None:
        _wrapper = LangGraphPostgresSaverWrapper()
    return _wrapper


async def get_langgraph_postgres_saver() -> Any | None:
    """Возвращает AsyncPostgresSaver или None при недоступности.

    Удобный fasade для caller'ов которые не хотят явно ловить
    :class:`LangGraphPostgresSaverUnavailable`.

    Returns:
        Экземпляр AsyncPostgresSaver либо None если flag выключен,
        пакет отсутствует или соединение не установлено.
    """
    wrapper = _factory()
    if not wrapper.enabled:
        return None
    try:
        return await wrapper.acquire()
    except LangGraphPostgresSaverUnavailable as exc:
        logger.debug("LangGraphPostgresSaver недоступен: %s", exc)
        return None


def reset_langgraph_postgres_saver() -> None:
    """Сбрасывает singleton (для тестов)."""
    global _wrapper
    _wrapper = None
