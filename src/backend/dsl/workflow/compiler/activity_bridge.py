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

from collections.abc import Awaitable, Callable
from typing import Any

from src.backend.core.logging import get_logger
from src.backend.core.security.activity_capability_guard import (
    capability_guarded_activity,
)
from src.backend.dsl.commands.action_registry import action_handler_registry
from src.backend.dsl.workflow.spec import (
    ActivityDeclaration,
    AgentInvokeDeclaration,
    SagaDeclaration,
    WorkflowDeclaration,
    WorkflowStep,
)
from src.backend.schemas.invocation import ActionCommandSchema

__all__ = (
    "ActivityBridge",
    "bridge_action_handler",
    "get_activity_callables",
    "LANGGRAPH_CHECKPOINT_GET_ACTIVITY",
    "LANGGRAPH_CHECKPOINT_PUT_ACTIVITY",
)


_logger = get_logger("workflow.compiler.activity_bridge")

# Stable activity names for LangGraph Checkpointer integration (S100 W1).
# These activities are NOT in any declaration — they are called by name from
# ``compile_agent_invoke_step`` when ``durable=True``. Worker must register
# them via :func:`register_langgraph_checkpoint_activities`.
LANGGRAPH_CHECKPOINT_GET_ACTIVITY = "_langgraph_checkpoint_get"
LANGGRAPH_CHECKPOINT_PUT_ACTIVITY = "_langgraph_checkpoint_put"


async def _agent_invoke_activity(payload: dict[str, Any]) -> Any:
    """Temporal activity-обёртка для вызова AIGateway.invoke (S27 W6).

    Выполняет stateless AI-инвокацию вне workflow-sandbox'а.
    Payload содержит сериализованный :class:`AIRequest` как dict.
    """

    from src.backend.core.ai.gateway import AIGateway
    from src.backend.core.ai.gateway_models import AIRequest

    # Reconstruct AIRequest from dict (dataclass)
    request = AIRequest(**payload)
    gateway = AIGateway()
    return await gateway.invoke(request)


async def _langgraph_checkpoint_get_activity(
    thread_id: str,
) -> dict[str, Any] | None:
    """Temporal activity для чтения LangGraph checkpoint по ``thread_id`` (S100 W1).

    Выполняется вне workflow-sandbox'а, поэтому может делать DB I/O.
    Используется в :func:`compile_agent_invoke_step` для resume в
    durable mode (``AgentInvokeDeclaration.durable=True``).

    Args:
        thread_id: LangGraph thread identifier (``{agent_id}:{correlation_id}``).

    Returns:
        Prior state (dict) если checkpoint существует, иначе ``None``.
        Возвращает ``None`` также если saver недоступен (flag OFF или
        langchain_postgres не установлен) — caller ОБРАБАТЫВАЕТ None как
        "первый запуск, нет prior state".
    """
    from src.backend.services.ai.agents.langgraph_postgres_saver import (
        get_langgraph_postgres_saver,
    )

    try:
        saver = await get_langgraph_postgres_saver()
        if saver is None:
            return None
        config: dict[str, Any] = {"configurable": {"thread_id": thread_id}}
        chk = await saver.aget(config)
        if chk is None:
            return None
        # AsyncPostgresSaver возвращает TypedDict-подобный объект; нормализуем
        # в plain dict для безопасной передачи через Temporal payload.
        return dict(chk) if hasattr(chk, "__iter__") else {"raw": chk}
    except Exception as exc:  # noqa: BLE001 — best-effort checkpoint load
        _logger.debug(
            "LangGraph checkpoint get(thread_id=%s) failed: %s", thread_id, exc
        )
        return None


async def _langgraph_checkpoint_put_activity(state: dict[str, Any]) -> bool:
    """Temporal activity для записи LangGraph checkpoint (S100 W1).

    Best-effort persist: при недоступности saver или ошибке записи
    возвращает ``False`` (НЕ raise) — durable mode degraded до
    stateless без прерывания workflow.

    Args:
        state: Сериализуемый dict с полями ``thread_id``, ``agent_id``,
            ``tenant_id``, ``prior_summary``, ``output_summary``, ``ts``.
            ``thread_id`` обязателен.

    Returns:
        ``True`` если checkpoint успешно записан, ``False`` иначе.
    """
    from src.backend.services.ai.agents.langgraph_postgres_saver import (
        get_langgraph_postgres_saver,
    )

    thread_id = state.get("thread_id") if isinstance(state, dict) else None
    if not thread_id:
        _logger.debug("LangGraph checkpoint put skipped: no thread_id in state")
        return False
    try:
        saver = await get_langgraph_postgres_saver()
        if saver is None:
            return False
        config: dict[str, Any] = {"configurable": {"thread_id": thread_id}}
        # AsyncPostgresSaver.aput signature: (config, values, metadata)
        await saver.aput(config, state, {})
        return True
    except Exception as exc:  # noqa: BLE001 — best-effort checkpoint save
        _logger.debug(
            "LangGraph checkpoint put(thread_id=%s) failed: %s", thread_id, exc
        )
        return False


def register_langgraph_checkpoint_activities(bridge: ActivityBridge) -> None:
    """Регистрирует LangGraph checkpoint activities в bridge (S100 W1).

    Worker-инициализатор должен вызвать эту функцию ДО
    :meth:`ActivityBridge.decorate` чтобы checkpoint activities попали
    в список регистрируемых в Temporal Worker. Без этого вызова
    ``workflow.execute_activity("_langgraph_checkpoint_get", ...)``
    упадёт с ``ActivityNotRegisteredError``.

    Args:
        bridge: ActivityBridge, в который добавляются 2 checkpoint
            activity-обёртки.
    """
    bridge.get(LANGGRAPH_CHECKPOINT_GET_ACTIVITY)
    bridge.get(LANGGRAPH_CHECKPOINT_PUT_ACTIVITY)


def bridge_action_handler(
    action_id: str, *, required_capabilities: tuple[str, ...] = ()
) -> Callable[..., Awaitable[Any]]:
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
        required_capabilities: Кортеж имён capability (V15 R-V15-1).
            При непустом значении функция оборачивается через
            :func:`capability_guarded_activity` ДО ``@activity.defn``.

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

    if required_capabilities:
        # Оборачиваем capability-guard'ом ДО @activity.defn — guard
        # должен сработать до Temporal-machinery (см. V15 R-V15-1).
        guarded = capability_guarded_activity(required_capabilities)(_activity_impl)
        # functools.wraps в decorator сохраняет __name__/__qualname__,
        # но мы явно копируем Temporal-маркер для совместимости.
        guarded.__activity_name__ = action_id  # type: ignore[attr-defined]
        return guarded
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

    def get(
        self, action_id: str, *, required_capabilities: tuple[str, ...] = ()
    ) -> Callable[..., Awaitable[Any]]:
        """Получить (или создать) activity-обёртку для ``action_id``.

        Args:
            action_id: Имя action.
            required_capabilities: Capability'и, требуемые активности.
                Применяется только при создании новой обёртки —
                cache-hit возвращает уже зарегистрированную callable.
        """
        wrapper = self._cache.get(action_id)
        if wrapper is None:
            if action_id == "_agent_invoke":
                wrapper = _agent_invoke_activity
                wrapper.__activity_name__ = action_id  # type: ignore[attr-defined]
            elif action_id == LANGGRAPH_CHECKPOINT_GET_ACTIVITY:
                # S100 W1: direct binding, чтобы cache identity match
                # ``is _langgraph_checkpoint_get_activity`` (тесты).
                wrapper = _langgraph_checkpoint_get_activity
                wrapper.__activity_name__ = action_id  # type: ignore[attr-defined]
            elif action_id == LANGGRAPH_CHECKPOINT_PUT_ACTIVITY:
                wrapper = _langgraph_checkpoint_put_activity
                wrapper.__activity_name__ = action_id  # type: ignore[attr-defined]
            else:
                wrapper = bridge_action_handler(
                    action_id, required_capabilities=required_capabilities
                )
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
                for action_id, capabilities in _iter_activity_specs(step):
                    if action_id in seen:
                        continue
                    seen.add(action_id)
                    result.append(
                        self.get(action_id, required_capabilities=capabilities)
                    )
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
                "temporalio SDK not installed. Install via `uv sync --extra workflow`."
            ) from exc

        for action_id, fn in list(self._cache.items()):
            if getattr(fn, "__temporal_activity_definition", None) is not None:
                continue
            decorated = activity.defn(name=action_id)(fn)
            self._cache[action_id] = decorated


def _iter_activity_names(step: WorkflowStep) -> list[str]:
    """Извлечь action_id всех activity-шагов из step (включая saga-вложения).

    Сохранён для backward-compatibility; внутренний код использует
    :func:`_iter_activity_specs` для получения capabilities.
    """
    return [name for name, _ in _iter_activity_specs(step)]


def _iter_activity_specs(step: WorkflowStep) -> list[tuple[str, tuple[str, ...]]]:
    """Извлечь ``(action_id, required_capabilities)`` всех activity-шагов.

    Args:
        step: Workflow-step (activity / saga / agent_invoke / иной).

    Returns:
        Список пар ``(action_id, capabilities-tuple)`` в порядке
        декларации (forward → compensate для saga).
    """
    if isinstance(step, ActivityDeclaration):
        return [(step.name, tuple(step.required_capabilities))]
    if isinstance(step, SagaDeclaration):
        specs: list[tuple[str, tuple[str, ...]]] = [
            (a.name, tuple(a.required_capabilities)) for a in step.forward
        ]
        specs.extend((a.name, tuple(a.required_capabilities)) for a in step.compensate)
        return specs
    if isinstance(step, AgentInvokeDeclaration):
        return [("_agent_invoke", ())]
    return []


def get_activity_callables(
    declarations: list[WorkflowDeclaration], *, bridge: ActivityBridge | None = None
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
