"""Unit-тесты S3 storage processors (S133 W4).

Покрытие:
    * to_s3 использует StorageFacade;
    * from_s3 использует StorageFacade;
    * ошибки backend'а помечают exchange failed.
"""

# ruff: noqa: S101

from __future__ import annotations

from typing import Any

import pytest

from src.backend.dsl.engine.context import ExecutionContext
from src.backend.dsl.engine.exchange import Exchange, Message
from src.backend.dsl.engine.processors.storage.s3 import FromS3Processor, ToS3Processor


def _exchange(
    body: Any = None, properties: dict[str, Any] | None = None
) -> Exchange[Any]:
    return Exchange(
        in_message=Message(body=body, headers={}), properties=properties or {}
    )


def _context(route_id: str = "route-1") -> ExecutionContext:
    return ExecutionContext(route_id=route_id)


@pytest.mark.asyncio
async def test_to_s3_uploads_via_facade(monkeypatch: pytest.MonkeyPatch) -> None:
    """to_s3 загружает данные через StorageFacade."""
    calls: list[dict[str, Any]] = []

    class _FakeFacade:
        plugin: str = ""

        async def upload(
            self, key: str, data: bytes, content_type: str | None = None
        ) -> str:
            calls.append({"key": key, "data": data, "content_type": content_type})
            return f"loc://{key}"

    def _fake_get_facade(context: ExecutionContext) -> Any:
        facade = _FakeFacade()
        facade.plugin = context.route_id
        return facade

    monkeypatch.setattr(
        "src.backend.dsl.engine.processors.storage.s3._get_storage_facade",
        _fake_get_facade,
    )

    proc = ToS3Processor(data_property="payload", key_from="target_key")
    ex = _exchange(properties={"payload": b"hello", "target_key": "out.txt"})
    ctx = _context()

    await proc.process(ex, ctx)

    assert ex.properties["s3_key"] == "loc://out.txt"
    assert calls[0]["key"] == "out.txt"
    assert calls[0]["data"] == b"hello"


@pytest.mark.asyncio
async def test_from_s3_downloads_via_facade(monkeypatch: pytest.MonkeyPatch) -> None:
    """from_s3 скачивает данные через StorageFacade."""

    class _FakeFacade:
        async def download(self, key: str) -> bytes:
            return b"file content"

    monkeypatch.setattr(
        "src.backend.dsl.engine.processors.storage.s3._get_storage_facade",
        lambda context: _FakeFacade(),
    )

    proc = FromS3Processor(key_from="s3_key", result_property="payload")
    ex = _exchange(properties={"s3_key": "in.txt"})
    ctx = _context()

    await proc.process(ex, ctx)

    assert ex.properties["payload"] == b"file content"


@pytest.mark.asyncio
async def test_to_s3_fails_exchange_on_backend_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Ошибка StorageFacade помечает exchange failed."""

    class _FakeFacade:
        async def upload(
            self, key: str, data: bytes, content_type: str | None = None
        ) -> str:
            raise RuntimeError("s3 down")

    monkeypatch.setattr(
        "src.backend.dsl.engine.processors.storage.s3._get_storage_facade",
        lambda context: _FakeFacade(),
    )

    proc = ToS3Processor()
    ex = _exchange(body=b"data", properties={"data": "out.txt"})
    ctx = _context()

    await proc.process(ex, ctx)

    assert ex.status == "failed"
    assert "s3 down" in (ex.error or "")
