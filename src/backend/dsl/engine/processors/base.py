from __future__ import annotations

import inspect
from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Any, ClassVar

from src.backend.core.logging import get_logger
from src.backend.core.types.side_effect import SideEffectKind
from src.backend.dsl.engine.exchange import Exchange

if TYPE_CHECKING:
    from src.backend.dsl.engine.context import ExecutionContext

__all__ = (
    "BaseProcessor",
    "CallableProcessor",
    "CapabilityGuardedProcessor",
    "ProcessorCallable",
    "SubPipelineExecutor",
    "emit_data_access_audit",
    "run_sub_processors",
)

ProcessorCallable = Callable[[Exchange[Any], "ExecutionContext"], Any | Awaitable[Any]]

_logger = get_logger(__name__)


def _capability_gate_enabled() -> bool:
    """Feature-flag ``dsl_capability_gate_enabled`` (ADR-0366).

    Returns:
        ``True`` — capability-гейт проверяется через runtime-резолвер;
        ``False`` — legacy-путь (поведение до ADR-0366).

    """
    try:
        from src.backend.core.config.features import feature_flags

        return bool(feature_flags.dsl_capability_gate_enabled)
    except Exception as exc:  # pragma: no cover — default-OFF (legacy-путь)
        _logger.debug("base_processor.capability_gate_flag_unavailable: %s", exc)
        return False


class BaseProcessor(ABC):
    """Базовый класс для всех DSL-процессоров.

    Class attributes:
        side_effect: Классификация побочных эффектов (W14.4).
            Default ``PURE`` — наследник обязан переопределить, если
            читает state или производит наблюдаемый внешний эффект.
            Используется engine для retry-стратегии и Saga compensation.
        compensatable: Можно ли откатить операцию (W14.4). Default ``True``.
            ``False`` для irreversible-операций (отправка email, физическое
            действие RPA). Saga блокирует compensate-цепочку, если
            процессор без compensatable.
        required_capability: Имя capability для auth-gate (``"rpa.file.list"``).
            Если задано — ``auth_check`` (helper) делает
            capability-check через runtime-резолвер (ADR-0366) перед
            выполнением. Если ``None`` — auth-check пропускается.
            (S172 Wave S2 — connector authorization.)
    """

    side_effect: ClassVar[SideEffectKind] = SideEffectKind.PURE
    compensatable: ClassVar[bool] = True
    required_capability: ClassVar[str | None] = None

    def __init__(self, name: str | None = None) -> None:
        self.name = name or self.__class__.__name__

    def set_result(self, exchange, target: str, value) -> None:  # type: ignore[no-untyped-def]
        """Записать значение в Exchange (body.<field> или property).

        Args:
            exchange: Текущий Exchange.
            target: Куда положить (body.<field>, properties.<name> или просто name).
            value: Значение.

        """
        if target.startswith("body."):
            field = target[len("body.") :]
            body = exchange.in_message.body
            if not isinstance(body, dict):
                body = {}
                exchange.in_message.body = body
            body[field] = value
            return
        if target.startswith("properties."):
            field = target[len("properties.") :]
            exchange.set_property(field, value)
            return
        exchange.set_property(target, value)

    async def auth_check(
        self,
        exchange: Exchange[Any],
        *,
        action: str = "execute",
        principal: str | None = None,
    ) -> bool:
        """Capability-gate для процессора (ADR-0366).

        Если процессор определяет :attr:`required_capability` — проверяет
        его. Наследники вызывают этот метод в начале :meth:`process` для
        per-step authorization.

        Два пути (feature-flag ``dsl_capability_gate_enabled``):

        * **включён** — runtime-резолвер
          (:mod:`src.backend.core.security.capabilities.runtime_resolver`):
          namespace = ``route_id`` роута → ``"core"`` (baseline) →
          fail-closed DENY; principal берётся из ``exchange.meta.principal``
          и **не** используется как namespace (ADR-0361);
        * **выключен** — legacy-путь
          (:func:`src.backend.core.security.connector_auth.check_source_capability`),
          поведение не меняется (rollout-рычаг).

        При denied — exchange переводится в ``failed`` (ADR-0393) и
        возвращается ``False``. Caller (subclass ``process()``) должен
        проверить return value и прервать выполнение (``return``).

        Почему именно ``failed``, а не ``stopped`` (ADR-0393, волна 18):
        раньше отказ записывался через ``set_error`` + ``stop()``, из-за
        чего статус exchange оставался ``processing``/``completed``:
        ``ExecutionEngine._finalize`` вызывал ``exchange.complete()``,
        который **обнулял** ``error`` → клиент получал «успех» (200),
        а SLO-метрика считала запрос ``is_error=False``. Отказ
        capability-гейта — это отказ авторизации, а не «успешный» маршрут.

        Args:
            exchange: DSL Exchange (для tenant_id + principal + audit).
            action: Действие (``"read"`` / ``"write"`` / ``"execute"``).
            principal: Caller identity. По умолчанию — ``exchange.meta.principal``,
                иначе ``"anonymous"``.

        Returns:
            ``True`` если доступ разрешён (или capability не задана),
            ``False`` если denied.

        """
        if self.required_capability is None:
            return True

        capability = self.required_capability
        meta_principal = getattr(exchange.meta, "principal", None)
        resolved_principal = (
            principal
            or (meta_principal if isinstance(meta_principal, str) else None)
            or "anonymous"
        )
        meta_tenant = getattr(exchange.meta, "tenant_id", None)
        tenant_id = meta_tenant if isinstance(meta_tenant, str) else None

        try:
            if _capability_gate_enabled():
                allowed, reason = self._check_via_runtime_resolver(
                    exchange,
                    capability=capability,
                    action=action,
                    principal=resolved_principal,
                    tenant_id=tenant_id,
                )
            else:
                allowed = await self._check_via_legacy_gateway(
                    capability=capability,
                    action=action,
                    principal=resolved_principal,
                    tenant_id=tenant_id,
                )
                reason = ""
        except Exception as exc:  # pragma: no cover — fail-closed
            exchange.fail(f"{self.name}: auth_check error: {exc}")
            exchange.stop()
            return False

        if not allowed:
            suffix = f" ({reason})" if reason else ""
            exchange.fail(f"{self.name}: capability '{capability}' denied{suffix}")
            exchange.stop()
            return False
        return True

    def _check_via_runtime_resolver(
        self,
        exchange: Exchange[Any],
        *,
        capability: str,
        action: str,
        principal: str,
        tenant_id: str | None,
    ) -> tuple[bool, str]:
        """Проверка capability через runtime-резолвер (ADR-0366).

        Returns:
            Кортеж ``(allowed, reason)``.
        """
        from src.backend.core.security.capabilities import runtime_resolver
        from src.backend.core.security.capabilities.tenant import SYSTEM_TENANT_ID

        request = runtime_resolver.CapabilityRequest(
            capability=capability,
            action=action,
            plugin=self._capability_namespace(exchange),
            scope=self._capability_scope(exchange),
            tenant=tenant_id or SYSTEM_TENANT_ID,
        )
        decision = runtime_resolver.check(request, principal=principal)
        return decision.allowed, decision.reason

    async def _check_via_legacy_gateway(
        self, *, capability: str, action: str, principal: str, tenant_id: str | None
    ) -> bool:
        """Legacy-проверка через ``AuthorizationGateway`` (до ADR-0366)."""
        from src.backend.core.security.connector_auth import check_source_capability

        return await check_source_capability(
            capability,
            action=action,
            principal=principal,
            extra_ctx={
                "tenant_id": tenant_id,
                "processor": self.name,
                "processor_class": type(self).__name__,
            },
        )

    def _capability_namespace(self, exchange: Exchange[Any]) -> str | None:
        """Namespace для capability-гейта — plugin роута (``route_id``).

        Наследник может переопределить (например, ``agent_dsl`` →
        ``"core"``). ``principal`` namespace'ом **не** является никогда.
        """
        return getattr(exchange.meta, "route_id", None)

    def _capability_scope(self, exchange: Exchange[Any]) -> str | None:
        """Scope для capability-проверки (по умолчанию — не уточнён).

        Наследник переопределяет для динамического scope (например,
        ``workflow_id`` из properties).
        """
        del exchange
        return None

    @abstractmethod
    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        """Метод process (см. signature)."""
        ...

    def to_spec(self) -> dict[str, Any] | None:
        """Возвращает YAML-spec процессора для round-trip сериализации.

        Returns:
            Словарь вида ``{method_name: {kwargs}}`` совместимый с YAML-лоадером,
            или ``None`` если процессор не поддерживает сериализацию.

        """
        return None


class CallableProcessor(BaseProcessor):
    """Адаптер, превращающий обычную функцию или coroutine в процессор."""

    def __init__(self, func: ProcessorCallable, name: str | None = None) -> None:
        super().__init__(name=name or getattr(func, "__name__", None))
        self._func = func

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        """Метод process (см. signature)."""
        result = self._func(exchange, context)
        if inspect.isawaitable(result):
            await result


class CapabilityGuardedProcessor(BaseProcessor):
    """Обёртка: capability-гейт перед делегированием legacy-процессору.

    Используется для шагов, чей процессор живёт в legacy-модуле и сам
    не проверяет ``required_capability`` (ADR-0393, волна 18 — дефект
    «обход гейта RPA»): ``fill_form`` / ``run_scenario`` из
    :mod:`src.backend.dsl.builders.ai_rpa.rpa` вели прямо в
    ``processors/web.py`` без какого-либо контроля доступа.

    Attributes:
        inner: Делегируемый процессор (legacy).
        action: Действие capability-гейта (``"invoke"`` / ``"read"``).

    """

    def __init__(
        self,
        inner: BaseProcessor,
        capability: str,
        *,
        action: str = "invoke",
        name: str | None = None,
    ) -> None:
        super().__init__(name=name or f"guarded:{inner.name}")
        self._inner = inner
        self._action = action
        # Инстансный override (ClassVar ``required_capability`` перекрывается
        # через ``__dict__`` — тот же механизм, что в ``eip/transformation.py``).
        self.__dict__["required_capability"] = capability

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        """Проверяет capability и делегирует внутреннему процессору.

        Args:
            exchange: Текущий Exchange.
            context: Контекст исполнения DSL-маршрута.

        """
        if not await self.auth_check(exchange, action=self._action):
            return
        await self._inner.process(exchange, context)


def emit_data_access_audit(
    exchange: Exchange[Any],
    *,
    event: str,
    capability: str,
    action: str,
    target: str,
    outcome: str = "granted",
) -> None:
    """Эмитит audit-событие доступа к данным (ADR-0393, дефект «аудит не пишется»).

    Событие **не содержит значений данных** — только метаданные доступа:
    capability, действие, цель (профиль БД / таблица) и tenant. Это
    позволяет построить журнал «кто к какой БД обращался», не превращая
    audit-лог в копию данных.

    Args:
        exchange: Текущий Exchange (источник tenant/principal/route).
        event: Имя audit-события (``"db.read"`` / ``"db.write"``).
        capability: Проверенная capability.
        action: Действие (``"read"`` / ``"write"``).
        target: Цель доступа (алиас ресурса: профиль БД или таблица).
        outcome: Итог (``"granted"`` / ``"denied"``).

    """
    details: dict[str, Any] = {
        "capability": capability,
        "action": action,
        "target": target,
        "route_id": exchange.meta.route_id,
    }
    if exchange.meta.tenant_id:
        details["tenant"] = exchange.meta.tenant_id
    try:
        from src.backend.core.audit.facade import emit_audit

        emit_audit(
            event=event,
            actor=exchange.meta.principal or exchange.meta.route_id or "system",
            resource=target,
            action=action,
            outcome=outcome,
            details=details,
        )
    except Exception as exc:  # pragma: no cover — аудит не должен ронять шаг
        _logger.debug("data_access_audit_failed: %s", exc)


class SubPipelineExecutor:
    """Устраняет дубликат «ExecutionEngine→execute→extract body» в 4 процессорах."""

    @staticmethod
    async def execute_route(
        route_id: str, body: Any, headers: dict[str, Any], context: ExecutionContext
    ) -> tuple[Any, str | None]:
        """Выполняет DSL route и возвращает (result_body, error_or_None)."""
        from src.backend.dsl.commands.registry import route_registry
        from src.backend.dsl.engine.execution_engine import ExecutionEngine

        pipeline = route_registry.get(route_id)
        engine = ExecutionEngine()
        sub = await engine.execute(
            pipeline, body=body, headers=dict(headers), context=context
        )
        result = sub.out_message.body if sub.out_message else sub.in_message.body
        return result, sub.error

    @staticmethod
    async def execute_route_safe(
        route_id: str, body: Any, headers: dict[str, Any], context: ExecutionContext
    ) -> tuple[str, Any, str | None]:
        """Безопасная версия — не бросает исключений."""
        try:
            result, error = await SubPipelineExecutor.execute_route(
                route_id, body, headers, context
            )
            return route_id, result, error
        except Exception as exc:
            return route_id, None, str(exc)


async def run_sub_processors(
    processors: list[BaseProcessor], exchange: Exchange[Any], context: ExecutionContext
) -> None:
    """Общий цикл выполнения sub-processor list с проверкой failed/stopped."""
    from src.backend.dsl.engine.exchange import ExchangeStatus

    for proc in processors:
        if exchange.status == ExchangeStatus.failed or exchange.stopped:
            break
        await proc.process(exchange, context)


def collect_route_results(
    raw_results: list[Any],
) -> tuple[dict[str, Any], dict[str, str]]:
    """Collect results from parallel route executions into results/errors dicts.

    Used by ScatterGather, RecipientList, Multicast to avoid code duplication.
    Each item in raw_results is either an Exception or (route_id, result, error_or_None).
    """
    results: dict[str, Any] = {}
    errors: dict[str, str] = {}
    for item in raw_results:
        if isinstance(item, Exception):
            errors["_exception"] = str(item)
        else:
            rid, result, error = item
            if error:
                errors[rid] = error
            else:
                results[rid] = result
    return results, errors


def handle_processor_error(process_method):
    """Декоратор для process() — ловит ImportError + Exception, записывает в exchange."""
    import functools

    @functools.wraps(process_method)
    async def wrapper(self, exchange: Exchange[Any], context: ExecutionContext) -> None:  # type: ignore[no-untyped-def]
        try:
            return await process_method(self, exchange, context)
        except ImportError as exc:
            exchange.set_error(f"{exc}")
            exchange.stop()
        except Exception as exc:
            exchange.set_error(f"{self.name} error: {exc}")
            exchange.stop()

    return wrapper
