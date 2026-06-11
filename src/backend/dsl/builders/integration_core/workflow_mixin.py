from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    pass

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.backend.dsl.builders.base import RouteBuilder


class WorkflowOpsMixin:
    """workflow ops (invoke/cancel/audit) для IntegrationCoreMixin. S62 W3 extraction."""

    __slots__ = ()

    def invoke_workflow(
        self,
        name: str,
        *,
        mode: str = "async-api",
        args: dict[str, Any] | None = None,
        namespace: str = "default",
        task_queue: str = "default",
        result_property: str = "workflow_result",
        invocation_id_property: str = "invocation_id",
        reply_timeout_seconds: float = 60.0,
        version: str | None = None,
    ) -> RouteBuilder:
        """Запуск Workflow (Temporal/LiteTemporal/PgRunner) — R-V15-7 / R-V15-9.

        Args:
            name: Логическое имя workflow.
            version: Опциональный SemVer-диапазон (например ``">=1.0,<2.0"``).
                При наличии ``workflow_versioning_routes=True`` — валидируется
                WorkflowLauncher.resolve() при старте workflow.
            mode: Режим вызова:

                * ``"sync"`` — ждёт terminal-статуса (без timeout).
                * ``"async-api"`` — возвращает handle сразу (default).
                * ``"async-reply"`` — fire-and-await с
                  ``reply_timeout_seconds`` timeout (Sprint 8A K3 W11).

            args: Базовые аргументы (если ``None`` — берётся
                ``in_message.body`` если dict).
            namespace: Workflow namespace (Temporal).
            task_queue: Workflow task queue (Temporal).
            result_property: Куда писать результат / handle.
            invocation_id_property: Куда писать workflow_id.
            reply_timeout_seconds: Таймаут для ``async-reply`` (default 60s).
                При timeout result_property получает ``{"status": "timeout",
                "workflow_id": ..., "timeout_seconds": ...}``.
        """
        from src.backend.dsl.engine.processors.invoke_workflow import (
            InvokeWorkflowProcessor,
        )

        return self._add(  # type: ignore[attr-defined]
            InvokeWorkflowProcessor(
                name,
                mode=mode,
                args=args,
                namespace=namespace,
                task_queue=task_queue,
                result_property=result_property,
                invocation_id_property=invocation_id_property,
                reply_timeout_seconds=reply_timeout_seconds,
                version=version,
            )
        )

    def cancel_workflow(
        self,
        workflow_id: str,
        *,
        reason: str = "",
        namespace: str = "default",
        result_property: str = "cancel_result",
    ) -> RouteBuilder:
        """Отмена workflow по ``workflow_id`` (Sprint 12 K3 W7).

        Args:
            workflow_id: Литерал или Ref-выражение
                ``"${body.invocation_id}"``.
            reason: Опциональная причина (для audit ``payload.reason``).
            namespace: Workflow namespace (Temporal).
            result_property: Куда писать результат
                (``{"cancelled": True, "workflow_id": ..., "reason": ...}``).
        """
        from src.backend.dsl.engine.processors.cancel_workflow import (
            CancelWorkflowProcessor,
        )

        return self._add(  # type: ignore[attr-defined]
            CancelWorkflowProcessor(
                workflow_id,
                reason=reason,
                namespace=namespace,
                result_property=result_property,
            )
        )

    def audit(
        self,
        *,
        action: str | None = None,
        action_from: str | None = None,
        actor: str = "system",
        actor_from: str | None = None,
        resource_from: str | None = None,
        outcome: str = "success",
        outcome_from: str | None = None,
        metadata_from: str | None = None,
        tenant_id_from: str | None = None,
        correlation_id_from: str | None = None,
        result_property: str = "audit_event_hash",
    ) -> RouteBuilder:
        """Записать событие в immutable audit log (Wave 5.1)."""
        from src.backend.dsl.engine.processors.audit import AuditProcessor

        return self._add(  # type: ignore[attr-defined]
            AuditProcessor(
                action=action,
                action_from=action_from,
                actor=actor,
                actor_from=actor_from,
                resource_from=resource_from,
                outcome=outcome,
                outcome_from=outcome_from,
                metadata_from=metadata_from,
                tenant_id_from=tenant_id_from,
                correlation_id_from=correlation_id_from,
                result_property=result_property,
            )
        )
