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

import importlib
import json
from collections.abc import Awaitable, Callable
from typing import Any, Literal

from src.backend.core.logging import get_logger
from src.backend.core.security.activity_capability_guard import (
    capability_guarded_activity,
)
from src.backend.dsl.commands.action_registry import action_handler_registry
from src.backend.dsl.workflow.spec import (
    ActivityDeclaration,
    AgentInvokeDeclaration,
    CallFunctionDeclaration,
    SagaDeclaration,
    SensorDeclaration,
    WorkflowDeclaration,
    WorkflowStep,
    is_call_function_ref,
)
from src.backend.schemas.invocation import ActionCommandMetaSchema, ActionCommandSchema

__all__ = (
    "INTERNAL_ACTIVITY_NAMES",
    "LANGGRAPH_CHECKPOINT_GET_ACTIVITY",
    "LANGGRAPH_CHECKPOINT_PUT_ACTIVITY",
    "ActivityBridge",
    "ActivityTarget",
    "UnknownActivityError",
    "bridge_action_handler",
    "bridge_call_function",
    "get_activity_callables",
    "resolve_activity_target",
)


_logger = get_logger("workflow.compiler.activity_bridge")

# Stable activity names for LangGraph Checkpointer integration (S100 W1).
# These activities are NOT in any declaration — they are called by name from
# ``compile_agent_invoke_step`` when ``durable=True``. Worker must register
# them via :func:`register_langgraph_checkpoint_activities`.
LANGGRAPH_CHECKPOINT_GET_ACTIVITY = "_langgraph_checkpoint_get"
LANGGRAPH_CHECKPOINT_PUT_ACTIVITY = "_langgraph_checkpoint_put"

#: Внутренние activity-функции моста: их нет в action-реестре, но они
#: регистрируются самим мостом (:meth:`ActivityBridge.get`). ADR-0424:
#: build-time валидация (``collect_activities(validate=True)``) обязана их
#: принимать — иначе любой workflow с ``agent_invoke``-шагом падает с
#: ``UnknownActivityError`` на старте worker'а.
#: Activity, которую генерирует компилятор шага ``reflect``
#: (``dsl/workflow/compiler/step_compilers/governance.py``).
MEMORY_REFLECT_ACTIVITY = "memory.reflect"

#: Activity, которую генерирует компилятор шага ``checkpoint``
#: (``dsl/workflow/compiler/step_compilers/flow.py``).
WORKFLOW_CHECKPOINT_PUT_ACTIVITY = "workflow.checkpoint.put"

INTERNAL_ACTIVITY_NAMES: frozenset[str] = frozenset(
    {
        "_agent_invoke",
        LANGGRAPH_CHECKPOINT_GET_ACTIVITY,
        LANGGRAPH_CHECKPOINT_PUT_ACTIVITY,
        MEMORY_REFLECT_ACTIVITY,
        WORKFLOW_CHECKPOINT_PUT_ACTIVITY,
    }
)


async def _agent_invoke_activity(payload: dict[str, Any]) -> Any:
    """Temporal activity-обёртка для вызова AIGateway.invoke (S27 W6).

    Выполняет stateless AI-инвокацию вне workflow-sandbox'а.
    Payload содержит сериализованный :class:`AIRequest` как dict.
    """
    from src.backend.core.ai.gateway_models import AIRequest
    from src.backend.services.ai.gateway_adapter import get_ai_gateway

    # Reconstruct AIRequest from dict (dataclass)
    request = AIRequest(**payload)
    gateway = get_ai_gateway()
    return await gateway.invoke(request)


async def _langgraph_checkpoint_get_activity(thread_id: str) -> dict[str, Any] | None:
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
    # Note (2026-10-14 audit Proposal 3): langgraph_postgres_saver удалён
    # (класс AsyncPostgresSaver отсутствует в langchain_postgres==0.0.17).
    # Возвращаем None — caller ОБРАБАТЫВАЕТ это как "первый запуск, нет prior state".
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
    # Note (2026-10-14 audit Proposal 3): langgraph_postgres_saver удалён
    # (класс AsyncPostgresSaver отсутствует в langchain_postgres==0.0.17).
    thread_id = state.get("thread_id") if isinstance(state, dict) else None
    if not thread_id:
        _logger.debug("LangGraph checkpoint put skipped: no thread_id in state")
        return False
    # saver удалён — checkpoint нельзя сохранить, возвращаем False
    # (best-effort: durable mode degraded до stateless).
    return False


async def _memory_reflect_activity(payload: dict[str, Any]) -> dict[str, Any]:
    """Temporal activity: запись reflection в memory-слой (ADR-0433).

    Пишет снимок outputs в LangMem по видам памяти из ``memory_writes``:
    ``episodic`` → ``remember_episode``, ``procedural`` → ``remember_procedure``.
    ``semantic`` требует embedding-вектора, который activity не считает —
    запись пропускается и попадает в ``skipped``.

    Args:
        payload: Поля ``source_step`` / ``memory_writes`` /
            ``outputs_snapshot`` / ``consolidation_policy``.

    Returns:
        ``{"reflected": bool, "written": [...], "skipped": [...]}``.

    """
    snapshot = payload.get("outputs_snapshot") or {}
    source_step = str(payload.get("source_step") or "workflow")
    requested = [str(item) for item in (payload.get("memory_writes") or [])]
    content = json.dumps(snapshot, default=str)[:8000]
    written: list[str] = []
    skipped: list[str] = []
    try:
        from src.backend.services.ai.memory.langmem_service import get_langmem_service

        service = get_langmem_service()
    except Exception as exc:  # noqa: BLE001 — memory недоступна → без записи
        _logger.warning("memory.reflect unavailable: %s", exc)
        return {"reflected": False, "written": [], "skipped": requested}

    for kind in requested:
        try:
            if kind == "episodic":
                await service.remember_episode(
                    agent_id=source_step,
                    content=content,
                    metadata={"source_step": source_step},
                )
                written.append(kind)
            elif kind == "procedural":
                await service.remember_procedure(
                    agent_id=source_step, name=source_step, steps=[content]
                )
                written.append(kind)
            else:
                # semantic требует embedding-вектора — считает AI-провайдер.
                skipped.append(kind)
        except Exception as exc:  # noqa: BLE001 — один вид памяти не роняет шаг
            _logger.warning("memory.reflect write failed (%s): %s", kind, exc)
            skipped.append(kind)
    return {"reflected": bool(written), "written": written, "skipped": skipped}


async def _workflow_checkpoint_put_activity(payload: dict[str, Any]) -> dict[str, Any]:
    """Temporal activity: явный checkpoint состояния workflow (ADR-0433).

    Durable-состояние в Temporal-пути обеспечивает собственный history
    Temporal'а, поэтому activity — best-effort: при отсутствии доступного
    хранилища возвращает ``{"persisted": False, ...}``, а компилятор шага
    пишет warning (не молчаливую потерю).

    Args:
        payload: Поля ``checkpoint_id`` / ``snapshot`` / ``metadata``.

    Returns:
        ``{"persisted": bool, "checkpoint_id": str, "reason": str | None}``.

    """
    checkpoint_id = str(payload.get("checkpoint_id") or "")
    if not checkpoint_id:
        return {
            "persisted": False,
            "checkpoint_id": "",
            "reason": "checkpoint_id отсутствует",
        }
    try:
        from src.backend.core.di.providers.workflow import (
            get_workflow_state_store_provider,
        )

        store = get_workflow_state_store_provider()
        save = getattr(store, "save_checkpoint", None)
        if callable(save):
            await save(checkpoint_id, payload.get("snapshot") or {})
            return {"persisted": True, "checkpoint_id": checkpoint_id, "reason": None}
        return {
            "persisted": False,
            "checkpoint_id": checkpoint_id,
            "reason": "хранилище checkpoint'ов не поддерживает save_checkpoint",
        }
    except Exception as exc:  # noqa: BLE001 — checkpoint best-effort
        _logger.warning("workflow.checkpoint.put unavailable: %s", exc)
        return {"persisted": False, "checkpoint_id": checkpoint_id, "reason": str(exc)}


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
        # P0 (cycle 59, parity с cycle 39/40/41/42): explicit system
        # principal для Temporal activity (background worker, no user context).
        command = ActionCommandSchema(
            action=action_id,
            payload=payload or {},
            meta=ActionCommandMetaSchema(
                principal=f"temporal_activity:{action_id}", permissions=[]
            ),
        )
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


def bridge_call_function(ref: str) -> Callable[..., Awaitable[Any]]:
    """Создать activity-обёртку над Python-функцией ``module:fn``.

    Идиома совпадает с route-DSL (``call_function('module:fn')``):
    функция принимает payload одним позиционным аргументом и может быть
    sync или async. Импорт модуля ленивый — на этапе регистрации activity
    модуль не импортируется.

    Args:
        ref: Ссылка ``module.path:function_name``.

    Returns:
        Async-callable, пригодный для регистрации в Temporal Worker.

    Raises:
        ValueError: Если ``ref`` не соответствует шаблону ``module:fn``.

    """

    async def _activity_impl(payload: dict[str, Any]) -> Any:
        module_name, fn_name = ref.split(":", 1)
        module = importlib.import_module(module_name)
        fn = getattr(module, fn_name, None)
        if fn is None or not callable(fn):
            raise ValueError(
                f"call_function: {ref!r} not found or not callable "
                f"(module={module_name!r}, attr={fn_name!r})"
            )
        result = fn(payload or {})
        if hasattr(result, "__await__"):
            result = await result
        return result

    _activity_impl.__name__ = f"call_function_{ref.replace('.', '_').replace(':', '_')}"
    _activity_impl.__qualname__ = f"activity::{ref}"
    _activity_impl.__activity_name__ = ref  # type: ignore[attr-defined]
    return _activity_impl


class UnknownActivityError(ValueError):
    """Имя activity не резолвится ни в action-реестре, ни в ``module:fn``.

    Выбрасывается на **build-time** (сбор activity-list для Worker'а),
    чтобы неполное имя в YAML-декларации падало с понятным сообщением,
    а не с ``KeyError`` внутри ``action_handler_registry.dispatch`` в
    рантайме workflow.
    """


#: Куда резолвится имя activity-шага.
ActivityTarget = Literal["action", "call_function", "internal"]


def resolve_activity_target(
    name: str, *, known_actions: tuple[str, ...] | None = None
) -> ActivityTarget:
    """Резолвить имя activity-шага против action-реестра / ``module:fn``.

    Args:
        name: Имя activity-шага из декларации.
        known_actions: Список известных action-имён (для сообщения об
            ошибке). Если ``None`` — берётся из глобального реестра.

    Returns:
        ``"action"`` — имя зарегистрировано в
        :data:`action_handler_registry`; ``"call_function"`` — это
        ссылка ``module:fn``; ``"internal"`` — внутренняя activity-функция
        моста (:data:`INTERNAL_ACTIVITY_NAMES`).

    Raises:
        UnknownActivityError: Если имя не резолвится ни одним из способов.

    """
    if is_call_function_ref(name):
        return "call_function"
    if name in INTERNAL_ACTIVITY_NAMES:
        return "internal"
    if action_handler_registry.is_registered(name):
        return "action"

    known = (
        known_actions
        if known_actions is not None
        else action_handler_registry.list_actions()
    )
    preview = ", ".join(known[:10]) if known else "<реестр пуст>"
    raise UnknownActivityError(
        f"Unknown activity {name!r}: не зарегистрирован в action-реестре "
        f"и не является 'call_function' ссылкой вида 'module:fn'. "
        f"Известные actions (первые 10): {preview}. "
        "Зарегистрируйте action (ActionHandlerRegistry) либо используйте "
        "step 'call_function' с ref='module.path:function_name'."
    )


def _unknown_activities_message(unknown: list[str]) -> str:
    """Собрать сообщение обо всех неизвестных activity-именах сразу.

    Args:
        unknown: Список неизвестных имён (в порядке декларации).

    Returns:
        Текст ошибки для :class:`UnknownActivityError`.

    """
    unique = list(dict.fromkeys(unknown))
    known = action_handler_registry.list_actions()
    preview = ", ".join(known[:10]) if known else "<реестр пуст>"
    return (
        f"Unknown activity names ({len(unique)}): {', '.join(unique)}. "
        "Ни одно из имён не зарегистрировано в action-реестре и не является "
        "'call_function' ссылкой вида 'module:fn'. "
        f"Известные actions (первые 10): {preview}. "
        "Зарегистрируйте action (ActionHandlerRegistry) либо используйте "
        "step 'call_function' с ref='module.path:function_name'."
    )


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
            action_id: Имя action либо ``call_function``-ссылка ``module:fn``.
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
            elif action_id == MEMORY_REFLECT_ACTIVITY:
                wrapper = _memory_reflect_activity
                wrapper.__activity_name__ = action_id  # type: ignore[attr-defined]
            elif action_id == WORKFLOW_CHECKPOINT_PUT_ACTIVITY:
                wrapper = _workflow_checkpoint_put_activity
                wrapper.__activity_name__ = action_id  # type: ignore[attr-defined]
            elif is_call_function_ref(action_id):
                # call_function-шаг (module:fn) — прямой вызов функции,
                # без обёртки в ActionHandlerRegistry.
                wrapper = bridge_call_function(action_id)
            else:
                wrapper = bridge_action_handler(
                    action_id, required_capabilities=required_capabilities
                )
            self._cache[action_id] = wrapper
        return wrapper

    def collect_activities(
        self, declarations: list[WorkflowDeclaration], *, validate: bool = False
    ) -> list[Callable[..., Awaitable[Any]]]:
        """Собрать уникальные activity-функции для списка деклараций.

        Args:
            declarations: Список workflow-деклараций.
            validate: ``True`` — резолвить каждое имя activity против
                action-реестра (``module:fn``-ссылки допускаются) и
                бросить :class:`UnknownActivityError` при неизвестном
                имени. Используется на build-time Worker'а, чтобы
                сломанная YAML-декларация падала сразу, а не в рантайме
                с ``KeyError`` внутри ``action_handler_registry``.

        Returns:
            Список activity-callable в порядке появления action_id
            (без дубликатов).

        Raises:
            UnknownActivityError: При ``validate=True`` и неизвестном имени
                activity.

        """
        seen: set[str] = set()
        unknown: list[str] = []
        result: list[Callable[..., Awaitable[Any]]] = []
        for decl in declarations:
            for step in decl.steps:
                for action_id, capabilities in _iter_activity_specs(step):
                    if validate and action_id not in seen:
                        try:
                            resolve_activity_target(action_id)
                        except UnknownActivityError:
                            unknown.append(action_id)
                    if action_id in seen:
                        continue
                    seen.add(action_id)
                    result.append(
                        self.get(action_id, required_capabilities=capabilities)
                    )
        if unknown:
            raise UnknownActivityError(_unknown_activities_message(unknown))
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


# D-AUDIT-10501 fix (cycle 105, WORKFLOW-P2-001): removed dead
# helper _iter_activity_names (определён 'для backward-compat' но
# не использовался НИГДЕ кроме собственного определения — verified
# через 'grep -rn _iter_activity_names src/ tests/'). Внутренний
# код использует _iter_activity_specs (ниже) для capabilities.


def _iter_activity_specs(step: WorkflowStep) -> list[tuple[str, tuple[str, ...]]]:
    """Извлечь ``(action_id, required_capabilities)`` всех activity-шагов.

    Args:
        step: Workflow-step (activity / call_function / saga / agent_invoke / иной).

    Returns:
        Список пар ``(action_id, capabilities-tuple)`` в порядке
        декларации (forward → compensate для saga).

    """
    if isinstance(step, ActivityDeclaration):
        return [(step.name, tuple(step.required_capabilities))]
    if isinstance(step, CallFunctionDeclaration):
        return [(step.ref, ())]
    if isinstance(step, SagaDeclaration):
        specs: list[tuple[str, tuple[str, ...]]] = [
            (a.name, tuple(a.required_capabilities)) for a in step.forward
        ]
        specs.extend((a.name, tuple(a.required_capabilities)) for a in step.compensate)
        return specs
    if isinstance(step, SensorDeclaration):
        # Sensor вызывает предикат как activity (``execute_activity``) —
        # без регистрации worker падает с ActivityNotRegisteredError.
        return [(step.predicate, ())]
    if isinstance(step, AgentInvokeDeclaration):
        return [("_agent_invoke", ())]
    return []


def get_activity_callables(
    declarations: list[WorkflowDeclaration],
    *,
    bridge: ActivityBridge | None = None,
    validate: bool = False,
) -> list[Callable[..., Awaitable[Any]]]:
    """Удобная функция: собрать activity-callable для Worker регистрации.

    Args:
        declarations: Список workflow-деклараций.
        bridge: Опциональный кастомный :class:`ActivityBridge`
            (нужен для тестов / shared-cache). Если ``None`` —
            создаётся новый одноразовый.
        validate: ``True`` — резолвить имена activity против
            action-реестра (см. :meth:`ActivityBridge.collect_activities`).

    Returns:
        Список callable, готовых к декорированию ``@activity.defn``
        (через :meth:`ActivityBridge.decorate`).

    """
    bridge = bridge or ActivityBridge()
    return bridge.collect_activities(declarations, validate=validate)
