"""`TemporalWorkflowBackend` — default impl `WorkflowBackend` (Wave D.2).

ADR-045: Temporal становится default workflow-движком; pg-runner
остаётся fallback для dev_light. Этот модуль — обёртка над
``temporalio.client.Client`` с lazy-import (heavy ~15-20MB SDK).

Семантика 1:1 с Protocol — никакого degraded поведения:

* ``signal_workflow`` → typed signal через client handle.
* ``query_workflow`` → typed query через client handle.
* ``cancel_workflow`` → ``handle.cancel()``.
* ``await_completion`` → ``handle.result()`` с typed-исключениями.
* ``replay`` → ``Replayer.replay_workflow(history)`` — CI versioning gate.

Worker registration (`register_workflow_class`) — отдельная задача
service-слоя; backend знает только client API.
"""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import TYPE_CHECKING, Any

from src.core.workflow.backend import WorkflowBackend, WorkflowHandle, WorkflowResult
from src.utilities.codecs.json import canonical_json_bytes

if TYPE_CHECKING:  # pragma: no cover
    from temporalio.client import Client as TemporalClient

__all__ = ("TemporalWorkflowBackend", "build_temporal_data_converter")


_logger = logging.getLogger("workflow.temporal_backend")


def build_temporal_data_converter() -> Any:
    """Собрать `DataConverter` поверх ``canonical_json_bytes``.

    Wave 7 / ADR-045: byte-stable сериализация для replay-корректности
    + интероперабельности с pg-runner snapshot'ами. Возвращает
    ``temporalio.converter.DataConverter`` с custom payload converter,
    использующим ``canonical_json_bytes`` (sort_keys=True, separators
    без пробелов).
    """
    from temporalio.api.common.v1 import Payload
    from temporalio.converter import (
        CompositePayloadConverter,
        DataConverter,
        EncodingPayloadConverter,
    )

    class _CanonicalJSONPayloadConverter(EncodingPayloadConverter):
        """Кодирует Python-значения через ``canonical_json_bytes``."""

        encoding = "json/canonical"

        def to_payload(self, value: Any) -> Payload | None:
            return Payload(
                metadata={"encoding": self.encoding.encode("utf-8")},
                data=canonical_json_bytes(value),
            )

        def from_payload(self, payload: Payload, type_hint: type | None = None) -> Any:
            import orjson  # lazy — orjson быстрее на decode

            return orjson.loads(payload.data) if payload.data else None

    return DataConverter(
        payload_converter_class=type(
            "_CompositeWithCanonical",
            (CompositePayloadConverter,),
            {
                "__init__": lambda self: CompositePayloadConverter.__init__(
                    self, _CanonicalJSONPayloadConverter()
                )
            },
        )
    )


class TemporalWorkflowBackend(WorkflowBackend):
    """`WorkflowBackend` поверх ``temporalio.client.Client``."""

    def __init__(
        self, *, client: TemporalClient, default_task_queue: str = "default"
    ) -> None:
        """Параметры:

        :param client: уже подключённый Temporal client (см.
            :func:`connect_temporal_client`).
        :param default_task_queue: fallback task_queue, если
            ``start_workflow`` вызван без явного значения.
        """
        self._client = client
        self._default_task_queue = default_task_queue

    @classmethod
    async def connect(
        cls,
        *,
        target: str = "localhost:7233",
        namespace: str = "default",
        default_task_queue: str = "default",
        api_key: str | None = None,
    ) -> "TemporalWorkflowBackend":
        """Lazy-import ``temporalio`` + connect.

        ``api_key`` для Temporal Cloud (mTLS-настройки — отдельный
        ADR-046 в R3).
        """
        try:
            from temporalio.client import Client
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError(
                "temporalio SDK not installed. Install via `uv sync --extra workflow`."
            ) from exc

        client = await Client.connect(
            target,
            namespace=namespace,
            api_key=api_key,
            data_converter=build_temporal_data_converter(),
        )
        return cls(client=client, default_task_queue=default_task_queue)

    async def start_workflow(
        self,
        *,
        workflow_name: str,
        workflow_id: str,
        input: dict[str, Any],
        namespace: str,
        task_queue: str,
        execution_timeout: timedelta | None = None,
    ) -> WorkflowHandle:
        """Запустить workflow через Temporal client.

        ``namespace`` — Temporal namespace (1:1 с tenant_id; "global" →
        "default" для backward-compat). Workflow class должен быть
        зарегистрирован в Worker (см. ``services/workflows/worker.py``
        в Wave D.3).
        """
        target_namespace = "default" if namespace == "global" else namespace
        # Temporal client привязан к одному namespace; multi-tenant —
        # отдельный client per namespace в R3 (см. ADR-045 §opens).
        if getattr(self._client, "namespace", target_namespace) != target_namespace:
            _logger.warning(
                "TemporalWorkflowBackend: namespace mismatch "
                "(client=%s, requested=%s) — using client's namespace",
                getattr(self._client, "namespace", "?"),
                target_namespace,
            )
        handle = await self._client.start_workflow(
            workflow_name,
            input,
            id=workflow_id,
            task_queue=task_queue or self._default_task_queue,
            execution_timeout=execution_timeout,
        )
        run_id = getattr(handle, "result_run_id", None) or getattr(
            handle, "first_execution_run_id", None
        )
        if not run_id:
            raise RuntimeError(
                f"Temporal start_workflow returned handle without run_id: {handle!r}"
            )
        return WorkflowHandle(
            workflow_id=workflow_id, run_id=run_id, namespace=namespace
        )

    async def signal_workflow(
        self, *, handle: WorkflowHandle, signal_name: str, payload: dict[str, Any]
    ) -> None:
        """Typed signal через ``client.get_workflow_handle``."""
        wf = self._client.get_workflow_handle(handle.workflow_id, run_id=handle.run_id)
        await wf.signal(signal_name, payload)

    async def query_workflow(
        self,
        *,
        handle: WorkflowHandle,
        query_name: str,
        args: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Typed query — read-only без побочных эффектов."""
        wf = self._client.get_workflow_handle(handle.workflow_id, run_id=handle.run_id)
        result = await wf.query(query_name, args or {})
        if isinstance(result, dict):
            return result
        return {"value": result}

    async def cancel_workflow(self, *, handle: WorkflowHandle) -> None:
        """Cancel через client handle."""
        wf = self._client.get_workflow_handle(handle.workflow_id, run_id=handle.run_id)
        await wf.cancel()

    async def await_completion(
        self, *, handle: WorkflowHandle, timeout: timedelta | None = None
    ) -> WorkflowResult:
        """Дождаться completion через ``handle.result()``.

        Маппинг исключений Temporal → ``WorkflowResult.failure``:

        * ``WorkflowFailureError`` → status=failed.
        * ``CancelledError`` → status=cancelled.
        * ``asyncio.TimeoutError`` (при ``timeout``) → status=timed_out.
        """
        from temporalio.exceptions import WorkflowAlreadyStartedError

        wf = self._client.get_workflow_handle(handle.workflow_id, run_id=handle.run_id)
        try:
            if timeout is not None:
                import asyncio

                output = await asyncio.wait_for(
                    wf.result(), timeout=timeout.total_seconds()
                )
            else:
                output = await wf.result()
        except WorkflowAlreadyStartedError as exc:  # pragma: no cover
            return WorkflowResult(
                output={},
                status="failed",
                failure={"type": "WorkflowAlreadyStartedError", "message": str(exc)},
            )
        except Exception as exc:
            return self._exception_to_result(exc)

        out_dict = output if isinstance(output, dict) else {"value": output}
        return WorkflowResult(output=out_dict, status="completed")

    async def replay(self, *, workflow_name: str, history: bytes) -> None:
        """Прогнать сериализованную историю через текущий код.

        Используется CI-replay-gate'ом: если код перестал быть
        совместим с зафиксированной историей — ``Replayer.replay``
        бросит ``WorkflowNonDeterminismError``.
        """
        try:
            from temporalio.client import WorkflowHistory
            from temporalio.worker import Replayer
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError("temporalio SDK not installed") from exc

        replayer = Replayer(workflows=[workflow_name])
        wf_history = WorkflowHistory.from_json(workflow_name, history.decode("utf-8"))
        await replayer.replay_workflow(wf_history)

    # --- helpers -------------------------------------------------------

    @staticmethod
    def _exception_to_result(exc: Exception) -> WorkflowResult:
        """Маппинг Temporal-исключений → ``WorkflowResult.failure``."""
        import asyncio

        try:
            from temporalio.exceptions import CancelledError as TCancelled
            from temporalio.exceptions import WorkflowFailureError
        except ImportError:  # pragma: no cover
            TCancelled = Exception
            WorkflowFailureError = Exception

        if isinstance(exc, asyncio.TimeoutError):
            return WorkflowResult(
                output={},
                status="timed_out",
                failure={
                    "type": "TimeoutError",
                    "message": "await_completion timed out",
                },
            )
        if isinstance(exc, TCancelled):
            return WorkflowResult(
                output={},
                status="cancelled",
                failure={"type": "Cancelled", "message": str(exc)},
            )
        if isinstance(exc, WorkflowFailureError):
            cause = getattr(exc, "cause", None)
            return WorkflowResult(
                output={},
                status="failed",
                failure={
                    "type": type(cause).__name__ if cause else "WorkflowFailureError",
                    "message": str(cause) if cause else str(exc),
                },
            )
        return WorkflowResult(
            output={},
            status="failed",
            failure={"type": type(exc).__name__, "message": str(exc)},
        )
