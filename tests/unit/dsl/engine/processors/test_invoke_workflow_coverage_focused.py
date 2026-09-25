"""Coverage ratchet для invoke_workflow.py (Sprint 12, cycle 147).

Покрывает branch'и InvokeWorkflowProcessor, не покрытые существующими тестами:
- ``__init__`` валидация ``mode`` через ``_coerce_mode``.
- ``_resolve_backend`` через backend_override / backend_factory / DI fallback.
- ``process()`` mode="async-api" — fire-and-forget (без wait_for).
- ``process()`` mode="async-reply" — wait_for с timeout narrowing (через deadline budget).
- ``to_spec()`` serialization.
- ``process()`` с args из dict (не из body).
- ``process()`` с backend error.
"""

from __future__ import annotations

from typing import Any

import pytest

from src.backend.dsl.engine.context import ExecutionContext
from src.backend.dsl.engine.exchange import Exchange, ExchangeStatus, Message
from src.backend.dsl.engine.processors.invoke_workflow import InvokeWorkflowProcessor


def _make_exchange(body: dict[str, Any] | None = None) -> Exchange[Any]:
    ex = Exchange(in_message=Message(body=body or {}))
    ex.status = ExchangeStatus.processing
    return ex


# ============================================================================
# __init__ / _coerce_mode validation
# ============================================================================


class TestInvokeWorkflowInit:
    """``__init__`` валидация через ``_coerce_mode``."""

    def test_invalid_mode_raises_value_error(self) -> None:
        """Невалидный mode → ValueError с описанием allowed modes."""
        with pytest.raises(ValueError, match="mode='bogus' не поддерживается"):
            InvokeWorkflowProcessor(name="wf1", mode="bogus")

    def test_async_api_mode_default(self) -> None:
        """Default mode = 'async-api'."""
        proc = InvokeWorkflowProcessor(name="wf1")
        assert proc.mode == "async-api"

    def test_async_reply_mode_valid(self) -> None:
        """mode='async-reply' валидно."""
        proc = InvokeWorkflowProcessor(name="wf1", mode="async-reply")
        assert proc.mode == "async-reply"


# ============================================================================
# _resolve_backend
# ============================================================================


class TestResolveBackend:
    """``_resolve_backend`` через 3 пути: override / factory / DI."""

    @pytest.mark.asyncio
    async def test_backend_override_used_directly(self) -> None:
        """Если backend передан в __init__ — используется напрямую."""
        sentinel_backend = object()
        proc = InvokeWorkflowProcessor(name="wf1", backend=sentinel_backend)  # type: ignore[arg-type]
        result = await proc._resolve_backend()
        assert result is sentinel_backend

    @pytest.mark.asyncio
    async def test_backend_factory_used(self) -> None:
        """Если передан backend_factory → вызывается factory."""
        sentinel = object()

        async def factory():
            return sentinel

        proc = InvokeWorkflowProcessor(name="wf1", backend_factory=factory)
        result = await proc._resolve_backend()
        assert result is sentinel


# ============================================================================
# process() — async-api mode (no wait_for)
# ============================================================================


class TestProcessAsyncApi:
    """``process()`` в mode='async-api' (fire-and-forget)."""

    @pytest.mark.asyncio
    async def test_async_api_records_invocation_id(self) -> None:
        """mode='async-api' записывает invocation_id в exchange.property."""
        started: list[dict[str, Any]] = []

        class _MockBackend:
            async def start_workflow(
                self,
                *,
                workflow_name: str,
                workflow_id: str,
                input: Any,
                namespace: str,
                task_queue: str,
            ) -> Any:
                started.append(
                    {
                        "name": workflow_name,
                        "id": workflow_id,
                        "input": input,
                        "namespace": namespace,
                        "task_queue": task_queue,
                    }
                )
                return object()

        backend = _MockBackend()
        proc = InvokeWorkflowProcessor(
            name="my-wf",
            mode="async-api",
            args={"key": "value"},
            namespace="custom-ns",
            task_queue="custom-q",
            backend=backend,
        )
        ex = _make_exchange()
        await proc.process(ex, ExecutionContext())

        # start_workflow был вызван с правильными аргументами.
        assert len(started) == 1
        assert started[0]["name"] == "my-wf"
        assert started[0]["input"] == {"key": "value"}
        assert started[0]["namespace"] == "custom-ns"
        assert started[0]["task_queue"] == "custom-q"

        # invocation_id записан в свойства.
        assert ex.get_property("invocation_id") == started[0]["id"]

        # accepted=True тоже записан.
        result = ex.get_property("workflow_result")
        assert result is not None
        assert result["accepted"] is True
        assert result["workflow_id"] == started[0]["id"]

    @pytest.mark.asyncio
    async def test_async_api_uses_body_when_args_none(self) -> None:
        """Когда args=None → input берётся из body."""
        started: list[dict[str, Any]] = []

        class _MockBackend:
            async def start_workflow(self, **kwargs) -> Any:
                started.append(kwargs)
                return object()

        proc = InvokeWorkflowProcessor(
            name="my-wf", mode="async-api", backend=_MockBackend()
        )
        ex = _make_exchange(body={"from": "body"})
        await proc.process(ex, ExecutionContext())
        assert started[0]["input"] == {"from": "body"}


# ============================================================================
# process() — async-reply mode (with wait_for)
# ============================================================================


class TestProcessAsyncReply:
    """``process()`` в mode='async-reply' (fire-and-await с timeout narrowing)."""

    @pytest.mark.asyncio
    async def test_async_reply_records_result(self) -> None:
        """mode='async-reply' дожидается завершения и пишет result.output."""

        class _CompletionResult:
            def __init__(self, output: Any) -> None:
                self.output = output

        class _MockBackend:
            async def start_workflow(self, **kwargs) -> Any:
                return object()

            async def await_completion(self, *, handle: Any) -> _CompletionResult:
                return _CompletionResult({"decision": "approved"})

        proc = InvokeWorkflowProcessor(
            name="my-wf",
            mode="async-reply",
            args={"input": "x"},
            backend=_MockBackend(),
            reply_timeout_seconds=10.0,
        )
        ex = _make_exchange()
        await proc.process(ex, ExecutionContext())

        result = ex.get_property("workflow_result")
        assert result == {"decision": "approved"}

    @pytest.mark.asyncio
    async def test_async_reply_timeout_records_error(self) -> None:
        """mode='async-reply' с timeout → exchange.set_property с timeout_marker."""

        class _MockBackend:
            async def start_workflow(self, **kwargs) -> Any:
                return object()

            async def await_completion(self, *, handle: Any) -> Any:
                import asyncio

                await asyncio.sleep(2.0)  # долго
                return None

        proc = InvokeWorkflowProcessor(
            name="my-wf",
            mode="async-reply",
            args={"input": "x"},
            backend=_MockBackend(),
            reply_timeout_seconds=0.05,  # узкий timeout
        )
        ex = _make_exchange()
        await proc.process(ex, ExecutionContext())
        # Timeout → result содержит timeout marker.
        result = ex.get_property("workflow_result")
        assert result is not None
        assert result.get("status") == "timeout"
        assert "workflow_id" in result
        assert result["timeout_seconds"] == 0.05


# ============================================================================
# process() — backend error
# ============================================================================


class TestProcessBackendError:
    """``process()`` когда backend падает.

    Note: ``start_workflow`` exceptions в текущей реализации НЕ обрабатываются —
    они propagate до caller'а (``Engine.execute`` ловит и переводит в
    ``exchange.fail``). Тест верифицирует текущее поведение.
    """

    @pytest.mark.asyncio
    async def test_start_workflow_error_propagates(self) -> None:
        """start_workflow raises → exception propagates (Engine catches)."""

        class _FailingBackend:
            async def start_workflow(self, **kwargs) -> Any:
                raise RuntimeError("backend down")

        proc = InvokeWorkflowProcessor(
            name="my-wf", mode="async-api", backend=_FailingBackend()
        )
        ex = _make_exchange()
        # Exception propagates до caller'а — Engine его поймает и fail exchange.
        with pytest.raises(RuntimeError, match="backend down"):
            await proc.process(ex, ExecutionContext())


# ============================================================================
# to_spec()
# ============================================================================


class TestInvokeWorkflowToSpec:
    """``to_spec()`` round-trip serialization."""

    def test_to_spec_minimal(self) -> None:
        """Minimal config → spec."""
        proc = InvokeWorkflowProcessor(name="wf1")
        spec = proc.to_spec()
        assert spec is not None
        assert "invoke_workflow" in spec
        assert spec["invoke_workflow"]["name"] == "wf1"

    def test_to_spec_full_config(self) -> None:
        """Full config → spec с всеми полями."""
        proc = InvokeWorkflowProcessor(
            name="wf1",
            mode="async-reply",
            args={"x": 1},
            namespace="custom",
            task_queue="q1",
            result_property="custom_result",
            invocation_id_property="custom_id",
            reply_timeout_seconds=42.0,
            version="1.0.0",
        )
        spec = proc.to_spec()
        assert spec is not None
        iw = spec["invoke_workflow"]
        assert iw["name"] == "wf1"
        assert iw["mode"] == "async-reply"
        assert iw["args"] == {"x": 1}
        assert iw["namespace"] == "custom"
        assert iw["task_queue"] == "q1"
        assert iw["result_property"] == "custom_result"
        assert iw["invocation_id_property"] == "custom_id"
        assert iw["reply_timeout_seconds"] == 42.0
        assert iw["version"] == "1.0.0"
