"""DSL processor ``invoke_workflow`` (Sprint 4 К3-B §6).

Связывает DSL pipeline с :class:`WorkflowBackend` — запускает workflow
по имени (название из реестра :data:`workflow_compiler_registry`) и
возвращает ``workflow_id`` либо результат, в зависимости от режима.

Режимы (контракт V15):

* ``sync`` — ждёт terminal-статуса, кладёт ``result`` в
  ``out_message.body`` и в ``exchange.property[result_property]``.
* ``async-api`` — стартует workflow и сразу возвращает
  ``invocation_id``/``workflow_id`` в ``property[invocation_id_property]``,
  не дожидаясь завершения.
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Any, Callable

from src.backend.core.workflow.backend import WorkflowBackend
from src.backend.dsl.engine.processors.base import BaseProcessor
from src.backend.dsl.registry import processor

if TYPE_CHECKING:
    from src.backend.dsl.engine.context import ExecutionContext
    from src.backend.dsl.engine.exchange import Exchange

__all__ = ("InvokeWorkflowProcessor",)


_ALLOWED_MODES = frozenset({"sync", "async-api"})


@processor(
    "invoke_workflow",
    namespace="core",
    spec_schema={
        "type": "object",
        "properties": {
            "name": {"type": "string"},
            "mode": {"type": "string", "enum": sorted(_ALLOWED_MODES)},
            "args": {"type": "object"},
            "namespace": {"type": "string"},
            "task_queue": {"type": "string"},
            "result_property": {"type": "string"},
            "invocation_id_property": {"type": "string"},
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
        backend: WorkflowBackend | None = None,
        backend_factory: Callable[[], Any] | None = None,
    ) -> None:
        super().__init__(name=f"invoke_workflow:{name}")
        self.workflow_name = name
        self.mode = self._coerce_mode(mode, workflow_name=name)
        self.args = args
        self.namespace_name = namespace
        self.task_queue = task_queue
        self.result_property = result_property
        self.invocation_id_property = invocation_id_property
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
        from src.backend.infrastructure.workflow.factory import (
            create_workflow_backend,
        )

        return await create_workflow_backend(kind="auto")

    async def process(
        self, exchange: "Exchange[Any]", context: "ExecutionContext"
    ) -> None:
        """Стартует workflow и пишет результат/handle в ``exchange``."""
        if self.args is not None:
            payload = dict(self.args)
        else:
            body = exchange.in_message.body
            payload = dict(body) if isinstance(body, dict) else {}

        backend = await self._resolve_backend()
        workflow_id = str(uuid.uuid4())

        handle = await backend.start_workflow(
            workflow_name=self.workflow_name,
            workflow_id=workflow_id,
            input=payload,
            namespace=self.namespace_name,
            task_queue=self.task_queue,
        )
        exchange.set_property(self.invocation_id_property, workflow_id)

        if self.mode == "async-api":
            exchange.set_property(
                self.result_property,
                {"accepted": True, "workflow_id": workflow_id},
            )
            return

        result = await backend.await_completion(handle=handle)
        exchange.set_property(self.result_property, result.output)
        exchange.set_out(
            body=result.output, headers=dict(exchange.in_message.headers)
        )

    def to_spec(self) -> dict[str, Any] | None:
        """Round-trip DSL-спецификация ``{"invoke_workflow": {...}}``."""
        spec: dict[str, Any] = {
            "name": self.workflow_name,
            "mode": self.mode,
        }
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
        return {"invoke_workflow": spec}
