"""LISTEN/NOTIFY push-path воркера: только PostgreSQL (smoke 2026-10-29).

Дефект: на профиле ``dev_light`` (SQLite) worker поднимал LISTEN-цикл с
DSN ``sqlite+aiosqlite:///...`` — asyncpg отвечал ``invalid DSN: scheme is
expected to be either "postgresql" or "postgres"``, и в лог уходила ошибка
на каждом старте.

Решение (осознанное): LISTEN/NOTIFY — механизм PostgreSQL, аналога в SQLite
нет. Worker на SQLite работает в backup-polling режиме (polling pending
инстансов), поэтому push-path отключается с понятным сообщением, а не с
ошибкой подключения.
"""

from __future__ import annotations

from typing import Any

import pytest

pytestmark = pytest.mark.unit


def _set_dsn(monkeypatch: pytest.MonkeyPatch, dsn: str) -> None:
    """Подменяет DSN основной БД в настройках."""
    from src.backend.core.config.settings import settings

    monkeypatch.setattr(
        type(settings.database),
        "async_connection_url",
        property(lambda self: dsn),
        raising=False,
    )


class TestResolveListenerDsn:
    """``_resolve_listener_dsn`` отдаёт DSN только для PostgreSQL."""

    def test_sqlite_dsn_is_rejected(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """SQLite-DSN → ``None`` (push-path отключён, не ошибка)."""
        from src.backend.infrastructure.workflow import worker

        _set_dsn(monkeypatch, "sqlite+aiosqlite:///./.run/dev.sqlite3")

        assert worker._resolve_listener_dsn() is None

    def test_postgres_asyncpg_dsn_is_translated(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """``postgresql+asyncpg://`` → plain ``postgresql://`` для asyncpg."""
        from src.backend.infrastructure.workflow import worker

        _set_dsn(monkeypatch, "postgresql+asyncpg://app:pwd@db:5432/app")

        assert worker._resolve_listener_dsn() == "postgresql://app:pwd@db:5432/app"

    def test_plain_postgres_dsn_is_kept(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Готовый ``postgresql://`` возвращается как есть."""
        from src.backend.infrastructure.workflow import worker

        _set_dsn(monkeypatch, "postgresql://app:pwd@db:5432/app")

        assert worker._resolve_listener_dsn() == "postgresql://app:pwd@db:5432/app"


class TestListenLoopSkipsNonPostgres:
    """LISTEN-цикл не подключается к не-PostgreSQL DSN."""

    async def test_listen_loop_does_not_connect(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Для не-PG DSN asyncpg не вызывается (цикл завершается сразу)."""
        import asyncpg

        from src.backend.infrastructure.workflow.runner import DurableWorkflowRunner

        calls: list[str] = []

        async def _fake_connect(dsn: str) -> Any:
            calls.append(dsn)
            raise AssertionError("asyncpg.connect не должен вызываться")

        monkeypatch.setattr(asyncpg, "connect", _fake_connect)

        from src.backend.infrastructure.workflow.runner import RunnerConfig

        runner = DurableWorkflowRunner(
            config=RunnerConfig(),
            executor=object(),  # type: ignore[arg-type]
            listener_dsn="sqlite+aiosqlite:///./.run/dev.sqlite3",
        )
        await runner._listen_loop()

        assert calls == []
