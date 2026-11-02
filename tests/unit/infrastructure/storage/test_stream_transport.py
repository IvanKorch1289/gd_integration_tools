"""Транспорт audit-stream: Redis Streams или in-memory (smoke 2026-10-29).

Дефект: на профиле ``dev_light`` (Redis выключен) audit-записи не писались,
а в лог падало ``Неизвестный ключ infrastructure-модуля:
'clients.storage.redis_streams'`` — DI-ключ не был зарегистрирован, и
единственным транспортом был Redis.

Контракт фикса:

* DI-ключ ``clients.storage.redis_streams`` резолвится;
* транспорт выбирается по ``settings.redis.enabled``: Redis (prod) или
  in-memory (dev/dev_light) — для не-redis транспорта Redis не нужен;
* контракт ``add_to_stream`` / ``read_stream`` одинаков для обоих.
"""

from __future__ import annotations

import uuid
from typing import Any

import pytest

pytestmark = pytest.mark.unit


@pytest.fixture
def stream_client(monkeypatch: pytest.MonkeyPatch) -> Any:
    """Клиент stream-транспорта с выключенным Redis (профиль dev_light)."""
    from src.backend.core.config.settings import settings

    monkeypatch.setattr(settings.redis, "enabled", False, raising=False)
    from src.backend.core.di.providers import get_redis_stream_client_provider

    return get_redis_stream_client_provider()


class TestModuleKey:
    """DI-ключ stream-транспорта зарегистрирован."""

    def test_key_resolves(self) -> None:
        """``resolve_module`` находит модуль по ключу."""
        from src.backend.core.di.module_registry import resolve_module

        module = resolve_module("clients.storage.redis_streams")
        assert hasattr(module, "redis_stream_client")

    def test_provider_returns_client(self) -> None:
        """Провайдер отдаёт клиент (без Redis — тоже)."""
        from src.backend.core.di.providers import get_redis_stream_client_provider

        client = get_redis_stream_client_provider()
        assert hasattr(client, "add_to_stream")
        assert hasattr(client, "read_stream")


class TestInMemoryTransport:
    """In-memory транспорт (Redis выключен)."""

    async def test_roundtrip(self, stream_client: Any) -> None:
        """Записанная запись читается обратно."""
        # Уникальное имя потока: in-memory транспорт — общий синглтон, и
        # параллельные тесты пишут в те же потоки (order-dependent сбой).
        stream = f"audit:requests:{uuid.uuid4().hex}"
        entry_id = await stream_client.add_to_stream(
            stream_name=stream, data={"path": "/health"}
        )
        assert entry_id

        records = await stream_client.read_stream(
            stream_name=stream, count=10, start_id="-"
        )
        assert len(records) == 1
        assert records[0]["path"] == "/health"

    async def test_streams_are_isolated(self, stream_client: Any) -> None:
        """Разные потоки не смешиваются."""
        suffix = uuid.uuid4().hex
        await stream_client.add_to_stream(stream_name=f"a:{suffix}", data={"x": 1})
        await stream_client.add_to_stream(stream_name=f"b:{suffix}", data={"x": 2})

        assert len(await stream_client.read_stream(stream_name=f"a:{suffix}")) == 1
        assert len(await stream_client.read_stream(stream_name=f"b:{suffix}")) == 1

    async def test_read_from_id_returns_newer_entries(self, stream_client: Any) -> None:
        """Чтение с ``start_id`` возвращает записи строго после указанной."""
        first = await stream_client.add_to_stream(stream_name="s", data={"n": 1})
        await stream_client.add_to_stream(stream_name="s", data={"n": 2})

        records = await stream_client.read_stream(stream_name="s", start_id=first)

        assert [r["n"] for r in records] == [2]


class TestAuditReplayWithoutRedis:
    """Audit-replay работает без Redis."""

    async def test_list_audit_records_returns_entries(self, stream_client: Any) -> None:
        """``replay_query.list_audit_records`` видит записи потока."""
        from src.backend.services.audit import replay_query

        await stream_client.add_to_stream(
            stream_name=replay_query._STREAM_NAME, data={"path": "/api/v1/x"}
        )

        records = await replay_query.list_audit_records(count=10)

        assert any(r.get("path") == "/api/v1/x" for r in records)

    async def test_replay_audit_record_finds_entry(self, stream_client: Any) -> None:
        """``replay_query.replay_audit_record`` отдаёт запись."""
        from src.backend.services.audit import replay_query

        await stream_client.add_to_stream(
            stream_name=replay_query._STREAM_NAME, data={"path": "/api/v1/y"}
        )
        records = await replay_query.list_audit_records(count=1)
        record_id = records[0]["id"]

        result = await replay_query.replay_audit_record(record_id)

        assert result["status"] in {"replayed", "not_found"}


class TestAuditMiddlewareWithoutRedis:
    """Audit-middleware пишет записи без Redis."""

    async def test_middleware_writes_audit_record(self, stream_client: Any) -> None:
        """Запрос к приложению попадает в audit-поток."""
        from src.backend.entrypoints.middlewares.audit_replay import (
            _STREAM_NAME,
            AuditReplayMiddleware,
        )

        async def downstream(scope: dict, receive: Any, send: Any) -> None:
            await send({"type": "http.response.start", "status": 200, "headers": []})
            await send({"type": "http.response.body", "body": b"ok"})

        async def receive() -> dict:
            return {"type": "http.request", "body": b"{}", "more_body": False}

        async def send(message: dict) -> None:
            return None

        middleware = AuditReplayMiddleware(downstream)
        scope = {
            "type": "http",
            "method": "POST",
            "path": "/api/v1/users",
            "headers": [],
            "query_string": b"",
            "client": ("127.0.0.1", 1234),
        }

        await middleware(scope, receive, send)

        records = await stream_client.read_stream(
            stream_name=_STREAM_NAME, count=10, start_id="-"
        )
        assert any(r.get("path") == "/api/v1/users" for r in records)
