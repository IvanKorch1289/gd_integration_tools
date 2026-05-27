"""DSL processor ``cancel_workflow`` (Sprint 12 K3 W7).

Связывает DSL pipeline с :class:`WorkflowBackend` — отменяет workflow
по его ``workflow_id``. Запись об отмене эмитится в
:class:`WorkflowAuditSink` (event_type=``workflow.cancel``) для
последующего анализа в admin-инвентаре (`/admin/workflow-audit`).

Контракт (V15 K3 W7):

* ``workflow_id`` либо литерал (для admin-action из YAML), либо
  Ref-нотация ``"${body.invocation_id}"`` (резолвится через
  ``exchange``).
* ``reason`` — произвольная строка, попадает в ``payload.reason``.
* Capability-check выполняется в :class:`WorkflowFacade`; если процессор
  работает без facade (dev-light / тесты), вызывается ``backend``
  напрямую.

Использование (Python builder)::

    RouteBuilder("admin_cancel") \\
        .from_("http:POST /admin/workflows/cancel") \\
        .cancel_workflow(
            workflow_id_ref="${body.workflow_id}",
            reason="admin_request",
        ) \\
        .to("response", code=204)

Использование (YAML)::

    steps:
      - cancel_workflow:
          workflow_id: ${body.parent_workflow_id}
          reason: "user_requested"
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, Callable

from src.backend.core.workflow.backend import WorkflowBackend, WorkflowHandle
from src.backend.dsl.engine.processors.base import BaseProcessor
from src.backend.dsl.registry import processor

if TYPE_CHECKING:
    from src.backend.dsl.engine.context import ExecutionContext
    from src.backend.dsl.engine.exchange import Exchange


__all__ = ("CancelWorkflowProcessor",)


_REF_PREFIX = "${"
_REF_SUFFIX = "}"


@processor(
    "cancel_workflow",
    namespace="core",
    spec_schema={
        "type": "object",
        "properties": {
            "workflow_id": {"type": "string"},
            "reason": {"type": "string"},
            "namespace": {"type": "string"},
            "result_property": {"type": "string"},
        },
        "required": ["workflow_id"],
    },
    meta={"tier": 1, "category": "workflow"},
)
class CancelWorkflowProcessor(BaseProcessor):
    """DSL-процессор отмены workflow по ``workflow_id``.

    Args:
        workflow_id: Литерал или Ref-выражение ``"${body.id}"``.
        reason: Опциональная причина (попадает в audit ``payload.reason``).
        namespace: Workflow namespace для backend lookup.
        result_property: Куда писать результат отмены.
        backend: Опциональный backend (DI/тесты); если ``None`` —
            ленивая фабрика ``create_workflow_backend("auto")``.
        backend_factory: Опциональная async-фабрика backend.
    """

    def __init__(
        self,
        workflow_id: str,
        *,
        reason: str = "",
        namespace: str = "default",
        result_property: str = "cancel_result",
        backend: WorkflowBackend | None = None,
        backend_factory: Callable[[], Any] | None = None,
    ) -> None:
        super().__init__(name=f"cancel_workflow:{workflow_id}")
        self.workflow_id_spec = workflow_id
        self.reason = reason
        self.namespace_name = namespace
        self.result_property = result_property
        self._backend_override = backend
        self._backend_factory = backend_factory

    @staticmethod
    def _resolve_ref(value: str, exchange: "Exchange[Any]") -> str:
        """Резолвит ``${body.path}`` / ``${property.path}`` через exchange."""
        if not (value.startswith(_REF_PREFIX) and value.endswith(_REF_SUFFIX)):
            return value
        inner = value[len(_REF_PREFIX) : -len(_REF_SUFFIX)].strip()
        head, _, tail = inner.partition(".")
        cursor: Any
        if head == "body":
            cursor = exchange.in_message.body
        elif head in {"property", "properties"}:
            cursor = dict(exchange.properties)
        elif head == "header":
            cursor = dict(exchange.in_message.headers)
        else:
            return value
        for part in tail.split(".") if tail else []:
            if isinstance(cursor, dict):
                cursor = cursor.get(part)
            else:
                cursor = getattr(cursor, part, None)
            if cursor is None:
                return value
        return str(cursor) if cursor is not None else value

    async def _resolve_backend(self) -> WorkflowBackend:
        if self._backend_override is not None:
            return self._backend_override
        if self._backend_factory is not None:
            return await self._backend_factory()
        from src.backend.infrastructure.workflow.factory import create_workflow_backend

        return await create_workflow_backend(kind="auto")

    async def process(
        self, exchange: "Exchange[Any]", context: "ExecutionContext"
    ) -> None:
        """Отменяет workflow и эмитит audit-event ``workflow.cancel``."""
        wf_id = self._resolve_ref(self.workflow_id_spec, exchange)
        if not wf_id:
            raise ValueError(
                f"cancel_workflow: пустой workflow_id (spec={self.workflow_id_spec!r})"
            )

        backend = await self._resolve_backend()
        handle = WorkflowHandle(
            workflow_id=wf_id, run_id=wf_id, namespace=self.namespace_name
        )
        await backend.cancel_workflow(handle=handle)

        try:
            from src.backend.services.audit.workflow_audit_sink import (
                get_workflow_audit_sink,
            )

            sink = get_workflow_audit_sink()
            if sink is not None:
                await sink.emit(
                    event_type="workflow.cancel",
                    workflow_id=wf_id,
                    tenant_id=None,
                    payload={
                        "reason": self.reason,
                        "caller": "dsl.cancel_workflow",
                        "namespace": self.namespace_name,
                    },
                )
        except Exception as _:  # noqa: BLE001
            pass

        exchange.set_property(
            self.result_property,
            {"cancelled": True, "workflow_id": wf_id, "reason": self.reason},
        )

    def to_spec(self) -> dict[str, Any] | None:
        """Round-trip DSL-спецификация ``{"cancel_workflow": {...}}``."""
        spec: dict[str, Any] = {"workflow_id": self.workflow_id_spec}
        if self.reason:
            spec["reason"] = self.reason
        if self.namespace_name != "default":
            spec["namespace"] = self.namespace_name
        if self.result_property != "cancel_result":
            spec["result_property"] = self.result_property
        return {"cancel_workflow": spec}
