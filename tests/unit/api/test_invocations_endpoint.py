"""Unit-тесты для REST-адаптера ``/api/v1/invocations`` (W22.2).

Не используют TestClient — напрямую вызывают handler-функции с
patched ``get_invoker`` / ``get_reply_channel_registry``. Это
достаточно для проверки контракта без поднятия full FastAPI lifespan.
"""

# ruff: noqa: S101

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import HTTPException, Response, status

from src.core.interfaces.invocation_reply import ReplyChannelKind
from src.core.interfaces.invoker import (
    InvocationMode,
    InvocationResponse,
    InvocationStatus,
)
from src.entrypoints.api.v1.endpoints.invocations import get_invocation, post_invocation
from src.infrastructure.messaging.invocation_replies import (
    MemoryReplyChannel,
    ReplyChannelRegistry,
)
from src.schemas.invocation_api import InvocationRequestSchema


def _patch_get_invoker(
    monkeypatch: pytest.MonkeyPatch, response: InvocationResponse
) -> MagicMock:
    invoker = MagicMock()
    invoker.invoke = AsyncMock(return_value=response)
    monkeypatch.setattr(
        "src.entrypoints.api.v1.endpoints.invocations.get_invoker",
        lambda: invoker,
        raising=False,
    )
    # get_invoker импортится внутри функции; patch'им src.services...
    monkeypatch.setattr(
        "src.services.execution.invoker.get_invoker",
        lambda: invoker,
    )
    return invoker


def _patch_registry(
    monkeypatch: pytest.MonkeyPatch, registry: ReplyChannelRegistry
) -> None:
    monkeypatch.setattr(
        "src.infrastructure.messaging.invocation_replies.get_reply_channel_registry",
        lambda: registry,
    )


class TestPostInvocation:
    async def test_sync_ok_returns_200(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        invoker_response = InvocationResponse(
            invocation_id="i-1",
            status=InvocationStatus.OK,
            result={"x": 1},
            mode=InvocationMode.SYNC,
        )
        _patch_get_invoker(monkeypatch, invoker_response)

        response = Response()
        body = InvocationRequestSchema(action="users.list", mode="sync")
        result = await post_invocation(body, response)

        assert result.status == "ok"
        assert result.invocation_id == "i-1"
        assert result.result == {"x": 1}
        # status_code не выставлен явно → FastAPI отдаст 200
        assert response.status_code is None or response.status_code == 200

    async def test_async_api_returns_202(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        invoker_response = InvocationResponse(
            invocation_id="i-2",
            status=InvocationStatus.ACCEPTED,
            mode=InvocationMode.ASYNC_API,
        )
        _patch_get_invoker(monkeypatch, invoker_response)

        response = Response()
        body = InvocationRequestSchema(action="x.y", mode="async-api")
        result = await post_invocation(body, response)

        assert result.status == "accepted"
        assert response.status_code == status.HTTP_202_ACCEPTED

    async def test_error_returns_payload_with_error(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        invoker_response = InvocationResponse(
            invocation_id="i-3",
            status=InvocationStatus.ERROR,
            error="boom",
            mode=InvocationMode.SYNC,
        )
        _patch_get_invoker(monkeypatch, invoker_response)

        response = Response()
        body = InvocationRequestSchema(action="x.y", mode="sync")
        result = await post_invocation(body, response)

        assert result.status == "error"
        assert result.error == "boom"

    async def test_invokes_with_correct_mode_and_reply_channel(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        invoker_response = InvocationResponse(
            invocation_id="i-4",
            status=InvocationStatus.ACCEPTED,
            mode=InvocationMode.STREAMING,
        )
        invoker = _patch_get_invoker(monkeypatch, invoker_response)

        response = Response()
        body = InvocationRequestSchema(
            action="x.stream", mode="streaming", reply_channel="ws"
        )
        await post_invocation(body, response)

        invoker.invoke.assert_awaited_once()
        request = invoker.invoke.call_args[0][0]
        assert request.mode is InvocationMode.STREAMING
        assert request.reply_channel == "ws"


class TestGetInvocation:
    async def test_returns_response_when_present(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        memory = MemoryReplyChannel()
        await memory.send(
            InvocationResponse(
                invocation_id="poll-1",
                status=InvocationStatus.OK,
                result={"done": True},
                mode=InvocationMode.ASYNC_API,
            )
        )
        registry = ReplyChannelRegistry()
        registry.register(memory)
        _patch_registry(monkeypatch, registry)

        result = await get_invocation("poll-1")
        assert result.status == "ok"
        assert result.result == {"done": True}

    async def test_returns_404_when_missing(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        registry = ReplyChannelRegistry()
        registry.register(MemoryReplyChannel())
        _patch_registry(monkeypatch, registry)

        with pytest.raises(HTTPException) as exc:
            await get_invocation("never-published")
        assert exc.value.status_code == status.HTTP_404_NOT_FOUND

    async def test_returns_503_if_api_channel_unavailable(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Registry без api-канала.
        registry = ReplyChannelRegistry()
        _patch_registry(monkeypatch, registry)

        with pytest.raises(HTTPException) as exc:
            await get_invocation("any-id")
        assert exc.value.status_code == status.HTTP_503_SERVICE_UNAVAILABLE


class TestSchemaValidation:
    """Pydantic-схемы корректно отклоняют неверные входные данные."""

    def test_empty_action_rejected(self) -> None:
        with pytest.raises(ValueError):
            InvocationRequestSchema(action="", mode="sync")

    def test_invalid_mode_rejected(self) -> None:
        with pytest.raises(ValueError):
            InvocationRequestSchema(action="x", mode="not-a-mode")  # type: ignore[arg-type]

    def test_known_modes_accepted(self) -> None:
        for mode in (
            "sync",
            "async-api",
            "async-queue",
            "deferred",
            "background",
            "streaming",
        ):
            schema = InvocationRequestSchema(action="x.y", mode=mode)  # type: ignore[arg-type]
            assert schema.mode == mode

    def test_default_mode_is_sync(self) -> None:
        schema = InvocationRequestSchema(action="x.y")
        assert schema.mode == "sync"

    @pytest.mark.parametrize("kind", [k.value for k in ReplyChannelKind])
    def test_reply_channel_optional(self, kind: str) -> None:
        schema = InvocationRequestSchema(
            action="x.y", mode="async-api", reply_channel=kind
        )
        assert schema.reply_channel == kind


class TestPayloadPassthrough:
    """Payload корректно проксируется в Invoker без изменений."""

    async def test_payload_preserved(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        invoker_response = InvocationResponse(
            invocation_id="i-pl",
            status=InvocationStatus.OK,
            result=None,
            mode=InvocationMode.SYNC,
        )
        invoker = _patch_get_invoker(monkeypatch, invoker_response)

        payload: dict[str, Any] = {"deeply": {"nested": [1, 2, {"key": "v"}]}}
        body = InvocationRequestSchema(
            action="deep.test", mode="sync", payload=payload
        )
        await post_invocation(body, Response())

        request = invoker.invoke.call_args[0][0]
        assert request.payload == payload
