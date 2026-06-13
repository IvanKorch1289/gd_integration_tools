"""DSL processor ``sub_workflow`` (Sprint 106 W3 — TD-006).

Семантический сахар над :class:`InvokeWorkflowProcessor` (mode=``"async-api"``)
для fire-and-forget запуска дочернего workflow в рамках parent workflow.

Ключевые отличия от ``invoke_workflow``:

* ``mode`` зафиксирован на ``"async-api"`` (sub-workflow по контракту
  неблокирующий — родитель продолжает работу после старта, не ожидая
  terminal-статуса). Синхронный режим = race conditions, поэтому запрещён.
* ``args`` обязателен (sub-workflow всегда имеет явные входные данные;
  неявный fallback на ``body`` здесь неуместен — sub-workflow это
  декомпозиция, а не трансформация in-place).
* ``parent_workflow_id`` / ``parent_correlation_id`` автоматически
  пробрасываются в ``metadata`` (для distributed tracing и audit
  вложенности child → parent).
* ``sub_workflow_id_property`` — отдельный DSL-property для удобной
  downstream-маршрутизации (``invocation_id`` родителя vs
  ``sub_workflow_id`` ребёнка).

Внутри ``SubWorkflowProcessor.process()`` делегирует на
:class:`InvokeWorkflowProcessor` с принудительным ``mode="async-api"``,
чтобы избежать дублирования бизнес-логики (S58 W1 LESSON: libraries >
custom — не воспроизводим 200+ LOC backend.start_workflow, а
переиспользуем InvokeWorkflowProcessor).
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Any

from src.backend.core.workflow.backend import WorkflowBackend
from src.backend.dsl.engine.processors.base import BaseProcessor
from src.backend.dsl.registry import processor

if TYPE_CHECKING:
    from src.backend.dsl.engine.context import ExecutionContext
    from src.backend.dsl.engine.exchange import Exchange

__all__ = ("SubWorkflowProcessor",)


_SUB_WORKFLOW_MODE = "async-api"


@processor(
    "sub_workflow",
    namespace="core",
    spec_schema={
        "type": "object",
        "properties": {
            "name": {"type": "string"},
            "args": {"type": "object"},
            "namespace": {"type": "string"},
            "task_queue": {"type": "string"},
            "sub_workflow_id_property": {"type": "string"},
            "result_property": {"type": "string"},
            "parent_workflow_id_property": {"type": "string"},
            "parent_correlation_id_property": {"type": "string"},
        },
        "required": ["name", "args"],
    },
    meta={"tier": 1, "category": "workflow"},
)
class SubWorkflowProcessor(BaseProcessor):
    """DSL-процессор fire-and-forget запуска sub-workflow.

    Args:
        name: Имя workflow (должно быть скомпилировано в
            :data:`workflow_compiler_registry` либо зарегистрировано в
            :class:`WorkflowBackend`).
        args: Аргументы запуска (обязательны; ``None`` запрещён).
        namespace: Workflow namespace для Temporal-backend'а.
        task_queue: Task queue.
        sub_workflow_id_property: Куда писать ``workflow_id`` ребёнка.
        result_property: Куда писать ``{"accepted": True,
            "workflow_id": ..., "parent_workflow_id": ...}``.
        parent_workflow_id_property: Property name, откуда взять
            ``workflow_id`` родителя (для tracing).
        parent_correlation_id_property: Property name, откуда взять
            ``correlation_id`` родителя.
        backend: Опциональный backend (DI/тесты).
        backend_factory: Опциональный factory (DI/тесты).
    """

    def __init__(
        self,
        name: str,
        args: dict[str, Any],
        *,
        namespace: str = "default",
        task_queue: str = "default",
        sub_workflow_id_property: str = "sub_workflow_id",
        result_property: str = "sub_workflow_result",
        parent_workflow_id_property: str = "workflow_id",
        parent_correlation_id_property: str = "correlation_id",
        backend: WorkflowBackend | None = None,
        backend_factory: Callable[[], Any] | None = None,
    ) -> None:
        if not args:
            raise ValueError(
                f"sub_workflow[{name!r}]: args обязательны (sub-workflow "
                f"должен иметь явные входные данные; используйте "
                f"invoke_workflow если нужен fallback на in_message.body)."
            )
        super().__init__(name=f"sub_workflow:{name}")
        self.workflow_name = name
        self.args = dict(args)
        self.namespace_name = namespace
        self.task_queue = task_queue
        self.sub_workflow_id_property = sub_workflow_id_property
        self.result_property = result_property
        self.parent_workflow_id_property = parent_workflow_id_property
        self.parent_correlation_id_property = parent_correlation_id_property
        self._backend_override = backend
        self._backend_factory = backend_factory

    async def _resolve_backend(self) -> WorkflowBackend:
        """Resolve backend с приоритетом: override → factory → factory.create."""
        if self._backend_override is not None:
            return self._backend_override
        if self._backend_factory is not None:
            return await self._backend_factory()
        from src.backend.infrastructure.workflow.factory import create_workflow_backend

        return await create_workflow_backend(kind="auto")

    async def process(
        self, exchange: Exchange[Any], context: ExecutionContext
    ) -> None:
        """Делегирует на :class:`InvokeWorkflowProcessor` (mode=async-api)."""
        from src.backend.dsl.engine.processors.invoke_workflow import (
            InvokeWorkflowProcessor,
        )

        parent_wf_id = exchange.get_property(self.parent_workflow_id_property)
        parent_corr_id = exchange.get_property(self.parent_correlation_id_property)

        args_with_parent: dict[str, Any] = dict(self.args)
        if parent_wf_id is not None and "_parent_workflow_id" not in args_with_parent:
            args_with_parent["_parent_workflow_id"] = parent_wf_id
        if parent_corr_id is not None and "_parent_correlation_id" not in args_with_parent:
            args_with_parent["_parent_correlation_id"] = parent_corr_id

        delegate = InvokeWorkflowProcessor(
            self.workflow_name,
            mode=_SUB_WORKFLOW_MODE,
            args=args_with_parent,
            namespace=self.namespace_name,
            task_queue=self.task_queue,
            result_property=self.result_property,
            invocation_id_property=self.sub_workflow_id_property,
            backend=self._backend_override,
            backend_factory=self._backend_factory,
        )
        await delegate.process(exchange, context)

    def to_spec(self) -> dict[str, Any] | None:
        """Round-trip DSL-спецификация ``{"sub_workflow": {...}}``."""
        spec: dict[str, Any] = {"name": self.workflow_name, "args": dict(self.args)}
        if self.namespace_name != "default":
            spec["namespace"] = self.namespace_name
        if self.task_queue != "default":
            spec["task_queue"] = self.task_queue
        if self.sub_workflow_id_property != "sub_workflow_id":
            spec["sub_workflow_id_property"] = self.sub_workflow_id_property
        if self.result_property != "sub_workflow_result":
            spec["result_property"] = self.result_property
        if self.parent_workflow_id_property != "workflow_id":
            spec["parent_workflow_id_property"] = self.parent_workflow_id_property
        if self.parent_correlation_id_property != "correlation_id":
            spec["parent_correlation_id_property"] = self.parent_correlation_id_property
        return {"sub_workflow": spec}
