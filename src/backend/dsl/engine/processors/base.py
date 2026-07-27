from __future__ import annotations

import inspect
from abc import ABC, abstractmethod
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Any, ClassVar

from src.backend.core.types.side_effect import SideEffectKind
from src.backend.dsl.engine.exchange import Exchange

if TYPE_CHECKING:
    from src.backend.dsl.engine.context import ExecutionContext

__all__ = (
    "BaseProcessor",
    "CallableProcessor",
    "ProcessorCallable",
    "SubPipelineExecutor",
    "run_sub_processors",
)

ProcessorCallable = Callable[[Exchange[Any], "ExecutionContext"], Any | Awaitable[Any]]


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
            capability-check через :class:`AuthorizationFacade` перед
            выполнением. Если ``None`` — auth-check пропускается.
            (S172 Wave S2 — connector authorization.)
    """

    side_effect: ClassVar[SideEffectKind] = SideEffectKind.PURE
    compensatable: ClassVar[bool] = True
    required_capability: ClassVar[str | None] = None

    def __init__(self, name: str | None = None) -> None:
        self.name = name or self.__class__.__name__

    def set_result(self, exchange, target: str, value) -> None:
        """Записать значение в Exchange (body.<field> или property).

        Args:
            exchange: Текущий Exchange.
            target: Куда положить (body.<field>, properties.<name> или просто name).
            value: Значение.
        """
        if target.startswith("body."):
            field = target[len("body."):]
            body = exchange.in_message.body
            if not isinstance(body, dict):
                body = {}
                exchange.in_message.body = body
            body[field] = value
            return
        if target.startswith("properties."):
            field = target[len("properties."):]
            exchange.set_property(field, value)
            return
        exchange.set_property(target, value)

    async def auth_check(
        self,
        exchange: Exchange[Any],
        *,
        action: str = "execute",
        principal: str = "anonymous",
    ) -> bool:
        """Capability-gate для процессора (S172 Wave S2).

        Если процессор определяет :attr:`required_capability` — проверяет
        его через :class:`AuthorizationFacade`. Наследники вызывают этот
        метод в начале :meth:`process` для per-step authorization.

        При denied — записывает ошибку в exchange и возвращает ``False``.
        Caller (subclass ``process()``) должен проверить return value
        и прервать выполнение (``return`` / ``exchange.stop()``).

        Args:
            exchange: DSL Exchange (для tenant_id + audit).
            action: Действие (``"read"`` / ``"write"`` / ``"execute"``).
            principal: Caller identity (default ``"anonymous"``).

        Returns:
            ``True`` если доступ разрешён (или capability не задана),
            ``False`` если denied.
        """
        if self.required_capability is None:
            return True

        try:
            from src.backend.core.security.connector_auth import check_source_capability

            tenant_id: str | None = None
            try:
                meta = getattr(exchange, "meta", None)
                if meta is not None:
                    tenant_id = getattr(meta, "tenant_id", None)
            except Exception:  # pragma: no cover
                tenant_id = None

            allowed = await check_source_capability(
                self.required_capability,
                action=action,
                principal=principal,
                extra_ctx={
                    "tenant_id": tenant_id,
                    "processor": self.name,
                    "processor_class": type(self).__name__,
                },
            )
            if not allowed:
                exchange.set_error(
                    f"{self.name}: capability '{self.required_capability}' denied"
                )
                exchange.stop()
                return False
            return True
        except Exception as exc:  # pragma: no cover — fail-closed
            exchange.set_error(
                f"{self.name}: auth_check error: {exc}"
            )
            exchange.stop()
            return False

    @abstractmethod
    async def process(
        self, exchange: Exchange[Any], context: ExecutionContext
    ) -> None: ...

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
        result = self._func(exchange, context)
        if inspect.isawaitable(result):
            await result


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
    async def wrapper(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        try:
            return await process_method(self, exchange, context)
        except ImportError as exc:
            exchange.set_error(f"{exc}")
            exchange.stop()
        except Exception as exc:
            exchange.set_error(f"{self.name} error: {exc}")
            exchange.stop()

    return wrapper
