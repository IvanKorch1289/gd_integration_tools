"""Activity Bridge — обёртки DSL action-handlers в Temporal ``@activity.defn``.

План V16.1 §4 Sprint 4 (К3): existing action-handlers
(:mod:`dsl.commands.setup.register_action_handlers`) автоматически
становятся Temporal-activities. Это убирает необходимость дублировать
бизнес-логику между REST/gRPC/MQ и workflow-движком.

Архитектурное правило (Temporal sandbox):
    * Activity функции живут вне workflow-сэндбокса и могут выполнять
      любой I/O. Workflow class лишь вызывает их через
      ``workflow.execute_activity(activity_name, ...)``.
    * Activity-bridge **лениво** импортирует action handler при первом
      выполнении (а не на этапе регистрации). Это позволяет
      compile_workflow быть быстрым и не тянуть тяжёлые сервисы.

Использование::

    bridge = ActivityBridge()
    activities = bridge.collect_activities([decl1, decl2])
    # activities — список callable, готовых к Worker регистрации.
"""

from __future__ import annotations

import logging
from typing import Any, Awaitable, Callable

from src.backend.dsl.commands.action_registry import action_handler_registry
from src.backend.dsl.workflow.spec import (
    ActivityDeclaration,
    SagaDeclaration,
    WorkflowDeclaration,
    WorkflowStep,
)
from src.backend.schemas.invocation import ActionCommandSchema

__all__ = ("ActivityBridge", "bridge_action_handler", "get_activity_callables")


_logger = logging.getLogger("workflow.compiler.activity_bridge")


def bridge_action_handler(action_id: str) -> Callable[..., Awaitable[Any]]:
    """Создать activity-функцию-обёртку поверх DSL action handler.

    Возвращаемая функция:
        * имеет ``__name__ = action_id`` (Temporal использует имя для
          поиска activity по строке);
        * лениво вызывает ``action_handler_registry.dispatch`` —
          handler регистрируется в startup до запуска worker'а;
        * принимает ``payload: dict[str, Any]`` и возвращает
          результат сервис-метода.

    Args:
        action_id: Имя action (например ``orders.create``).

    Returns:
        Callable, который Temporal worker может зарегистрировать как
        activity. Имя совпадает с ``action_id``.

    Raises:
        Не raise на этапе регистрации — отсутствие handler проявится
        в runtime ``KeyError`` при первом вызове activity.
    """

    async def _activity_impl(payload: dict[str, Any]) -> Any:
        command = ActionCommandSchema(action=action_id, payload=payload or {})
        return await action_handler_registry.dispatch(command)

    _activity_impl.__name__ = action_id.replace(".", "_")
    _activity_impl.__qualname__ = f"activity::{action_id}"
    # Сохраняем оригинальное имя — Temporal активирует activity по строке.
    _activity_impl.__activity_name__ = action_id  # type: ignore[attr-defined]
    return _activity_impl


class ActivityBridge:
    """Сборщик activity-функций для регистрации в Temporal Worker.

    Для каждой :class:`ActivityDeclaration` (включая вложенные в
    :class:`SagaDeclaration`) создаётся уникальная обёртка. Обёртки
    кешируются по ``action_id`` — повторная компиляция того же
    workflow не плодит дубликаты.
    """

    def __init__(self) -> None:
        self._cache: dict[str, Callable[..., Awaitable[Any]]] = {}

    def get(self, action_id: str) -> Callable[..., Awaitable[Any]]:
        """Получить (или создать) activity-обёртку для ``action_id``."""
        wrapper = self._cache.get(action_id)
        if wrapper is None:
            wrapper = bridge_action_handler(action_id)
            self._cache[action_id] = wrapper
        return wrapper

    def collect_activities(
        self, declarations: list[WorkflowDeclaration]
    ) -> list[Callable[..., Awaitable[Any]]]:
        """Собрать уникальные activity-функции для списка деклараций.

        Args:
            declarations: Список workflow-деклараций.

        Returns:
            Список activity-callable в порядке появления action_id
            (без дубликатов).
        """
        seen: set[str] = set()
        result: list[Callable[..., Awaitable[Any]]] = []
        for decl in declarations:
            for step in decl.steps:
                for action_id in _iter_activity_names(step):
                    if action_id in seen:
                        continue
                    seen.add(action_id)
                    result.append(self.get(action_id))
        return result

    def decorate(self) -> None:
        """Применить ``@activity.defn(name=action_id)`` ко всем кеш-обёрткам.

        Lazy-import ``temporalio`` — вызывается перед регистрацией в
        Worker. Идемпотентен: повторный вызов не добавляет декораторы.
        """
        try:
            from temporalio import activity
        except ImportError as exc:  # pragma: no cover
            raise RuntimeError(
                "temporalio SDK not installed. "
                "Install via `uv sync --extra workflow`."
            ) from exc

        for action_id, fn in list(self._cache.items()):
            if getattr(fn, "__temporal_activity_definition", None) is not None:
                continue
            decorated = activity.defn(name=action_id)(fn)
            self._cache[action_id] = decorated


def _iter_activity_names(step: WorkflowStep) -> list[str]:
    """Извлечь action_id всех activity-шагов из step (включая saga-вложения)."""
    if isinstance(step, ActivityDeclaration):
        return [step.name]
    if isinstance(step, SagaDeclaration):
        names = [a.name for a in step.forward]
        names.extend(a.name for a in step.compensate)
        return names
    return []


def get_activity_callables(
    declarations: list[WorkflowDeclaration],
    *,
    bridge: ActivityBridge | None = None,
) -> list[Callable[..., Awaitable[Any]]]:
    """Удобная функция: собрать activity-callable для Worker регистрации.

    Args:
        declarations: Список workflow-деклараций.
        bridge: Опциональный кастомный :class:`ActivityBridge`
            (нужен для тестов / shared-cache). Если ``None`` —
            создаётся новый одноразовый.

    Returns:
        Список callable, готовых к декорированию ``@activity.defn``
        (через :meth:`ActivityBridge.decorate`).
    """
    bridge = bridge or ActivityBridge()
    return bridge.collect_activities(declarations)
