"""DSL processor ``invoke_workflow`` (Sprint 4 К3-B §6; Sprint 8A K3 W11).

Связывает DSL pipeline с :class:`WorkflowBackend` — запускает workflow
по имени (название из реестра :data:`workflow_compiler_registry`) и
возвращает ``workflow_id`` либо результат, в зависимости от режима.

Режимы (контракт V15 + Sprint 8A K3 W11):

* ``sync`` — ждёт terminal-статуса, кладёт ``result`` в
  ``out_message.body`` и в ``exchange.property[result_property]``.
* ``async-api`` — стартует workflow и сразу возвращает
  ``invocation_id``/``workflow_id`` в ``property[invocation_id_property]``,
  не дожидаясь завершения.
* ``async-reply`` — fire-and-await: запускает workflow и ждёт terminal-
  статуса с настраиваемым timeout. По истечению timeout — пишет
  ``status: timeout`` в result_property без отмены workflow. Удобен для
  long-running workflows с SLA-таймаутами в DSL-route.
"""

from __future__ import annotations

import asyncio
import uuid
from typing import TYPE_CHECKING, Any, Callable

from src.backend.core.workflow.backend import WorkflowBackend
from src.backend.dsl.engine.processors.base import BaseProcessor
from src.backend.dsl.registry import processor

if TYPE_CHECKING:
    from src.backend.dsl.engine.context import ExecutionContext
    from src.backend.dsl.engine.exchange import Exchange

__all__ = ("InvokeWorkflowProcessor",)


_ALLOWED_MODES = frozenset({"sync", "async-api", "async-reply"})
_DEFAULT_REPLY_TIMEOUT_SECONDS = 60.0


@processor(
    "invoke_workflow",
    namespace="core",
    spec_schema={
        "type": "object",
        "properties": {
            "name": {"type": "string"},
            "version": {"type": "string"},
            "mode": {"type": "string", "enum": sorted(_ALLOWED_MODES)},
            "args": {"type": "object"},
            "namespace": {"type": "string"},
            "task_queue": {"type": "string"},
            "result_property": {"type": "string"},
            "invocation_id_property": {"type": "string"},
            "reply_timeout_seconds": {"type": "number", "exclusiveMinimum": 0},
        },
        "required": ["name"],
    },
    meta={"tier": 1, "category": "workflow"},
)
class InvokeWorkflowProcessor(BaseProcessor):
    """DSL-процессор запуска workflow через :class:`WorkflowBackend`.

    Args:
        name: Имя workflow (логическое — должно быть скомпилировано в
            :data:`workflow_compiler_registry` либо зарегистрировано
            непосредственно в backend'е).
        mode: ``sync`` (ждать completion) или ``async-api`` (fire-and-
            return-handle). По умолчанию ``async-api``.
        args: Базовые аргументы запуска (если ``None`` — берётся
            ``exchange.in_message.body`` если это dict, иначе ``{}``).
        namespace: Workflow namespace для Temporal-backend'а.
            По умолчанию ``"default"``.
        task_queue: Task queue. По умолчанию ``"default"``.
        result_property: Куда писать результат при ``mode=sync``.
        invocation_id_property: Куда писать ``workflow_id``.
        backend: Опциональный backend (для DI/тестов). При ``None`` —
            создаётся через :func:`create_workflow_backend` (``auto``).
    """

    def __init__(
        self,
        name: str,
        *,
        mode: str = "async-api",
        args: dict[str, Any] | None = None,
        namespace: str = "default",
        task_queue: str = "default",
        result_property: str = "workflow_result",
        invocation_id_property: str = "invocation_id",
        reply_timeout_seconds: float = _DEFAULT_REPLY_TIMEOUT_SECONDS,
        backend: WorkflowBackend | None = None,
        backend_factory: Callable[[], Any] | None = None,
        version: str | None = None,
    ) -> None:
        super().__init__(name=f"invoke_workflow:{name}")
        self.workflow_name = name
        self.version = version
        self.mode = self._coerce_mode(mode, workflow_name=name)
        self.args = args
        self.namespace_name = namespace
        self.task_queue = task_queue
        self.result_property = result_property
        self.invocation_id_property = invocation_id_property
        self.reply_timeout_seconds = reply_timeout_seconds
        self._backend_override = backend
        self._backend_factory = backend_factory

    @staticmethod
    def _coerce_mode(value: str, *, workflow_name: str) -> str:
        if value not in _ALLOWED_MODES:
            allowed = ", ".join(sorted(_ALLOWED_MODES))
            raise ValueError(
                f"invoke_workflow[{workflow_name}]: mode={value!r} не поддерживается. "
                f"Допустимо: {allowed}."
            )
        return value

    async def _resolve_backend(self) -> WorkflowBackend:
        if self._backend_override is not None:
            return self._backend_override
        if self._backend_factory is not None:
            return await self._backend_factory()
        from src.backend.infrastructure.workflow.factory import create_workflow_backend

        return await create_workflow_backend(kind="auto")

    async def _resolve_workflow_version(self) -> str:
        """Resolve workflow version using WorkflowLauncher if flag enabled.

        Returns the resolved version string. If version is None or flag is disabled,
        returns the original workflow name (no version resolution).
        """
        if not self.version:
            return self.workflow_name

        try:
            from src.backend.core.config.features import feature_flags

            if not feature_flags.workflow_versioning_routes:
                return self.workflow_name
        except Exception as _:
            return self.workflow_name

        try:
            from src.backend.dsl.workflow.launcher import (
                WorkflowLauncher,
                WorkflowResolutionError,
            )

            launcher = WorkflowLauncher()
            resolved = launcher.resolve(self.workflow_name, self.version)
            return resolved.name
        except WorkflowResolutionError:
            # Fallback to original name if resolution fails
            return self.workflow_name

    async def process(
        self, exchange: "Exchange[Any]", context: "ExecutionContext"
    ) -> None:
        """Стартует workflow и пишет результат/handle в ``exchange``."""
        if self.args is not None:
            payload = dict(self.args)
        else:
            body = exchange.in_message.body
            payload = dict(body) if isinstance(body, dict) else {}

        # Resolve workflow name (may include version spec)
        workflow_name = await self._resolve_workflow_version()

        backend = await self._resolve_backend()
        workflow_id = str(uuid.uuid4())

        handle = await backend.start_workflow(
            workflow_name=workflow_name,
            workflow_id=workflow_id,
            input=payload,
            namespace=self.namespace_name,
            task_queue=self.task_queue,
        )
        exchange.set_property(self.invocation_id_property, workflow_id)

        if self.mode == "async-api":
            exchange.set_property(
                self.result_property, {"accepted": True, "workflow_id": workflow_id}
            )
            return

        if self.mode == "async-reply":
            # Sprint 8A K3 W11: fire-and-await с настраиваемым timeout.
            try:
                result = await asyncio.wait_for(
                    backend.await_completion(handle=handle),
                    timeout=self.reply_timeout_seconds,
                )
            except asyncio.TimeoutError:
                exchange.set_property(
                    self.result_property,
                    {
                        "status": "timeout",
                        "workflow_id": workflow_id,
                        "timeout_seconds": self.reply_timeout_seconds,
                    },
                )
                return
            exchange.set_property(self.result_property, result.output)
            exchange.set_out(
                body=result.output, headers=dict(exchange.in_message.headers)
            )
            return

        # mode == "sync"
        result = await backend.await_completion(handle=handle)
        exchange.set_property(self.result_property, result.output)
        exchange.set_out(body=result.output, headers=dict(exchange.in_message.headers))

    def to_spec(self) -> dict[str, Any] | None:
        """Round-trip DSL-спецификация ``{"invoke_workflow": {...}}``."""
        spec: dict[str, Any] = {"name": self.workflow_name, "mode": self.mode}
        if self.version:
            spec["version"] = self.version
        if self.args is not None:
            spec["args"] = dict(self.args)
        if self.namespace_name != "default":
            spec["namespace"] = self.namespace_name
        if self.task_queue != "default":
            spec["task_queue"] = self.task_queue
        if self.result_property != "workflow_result":
            spec["result_property"] = self.result_property
        if self.invocation_id_property != "invocation_id":
            spec["invocation_id_property"] = self.invocation_id_property
        if (
            self.mode == "async-reply"
            and self.reply_timeout_seconds != _DEFAULT_REPLY_TIMEOUT_SECONDS
        ):
            spec["reply_timeout_seconds"] = self.reply_timeout_seconds
        return {"invoke_workflow": spec}
