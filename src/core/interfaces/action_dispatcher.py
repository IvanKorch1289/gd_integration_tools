"""Контракт ActionDispatcher / ActionGateway (W14.1 + W14.1.A).

Action отделён от транспорта: одна и та же бизнес-команда может быть
запущена из HTTP/gRPC/Queue/WS/Schedule. Реализация — в
``services/execution/action_dispatcher.py``.

Wave 14.1.A (Phase A) — расширение контракта под Gateway-функциональность:

* :class:`ActionMetadata` — расширенные метаданные action (input/output
  schema, transports, side_effect, idempotent, permissions, rate_limit,
  timeout_ms, deprecated, since_version, error_types).
* :class:`DispatchContext` — контекст вызова (correlation_id, tenant_id,
  user_id, idempotency_key, source, trace_parent).
* :class:`ActionResult` — унифицированный envelope (success, data, error,
  metadata).
* :class:`ActionError` — структура ошибки (code, message, details,
  recoverable).
* :class:`ActionGatewayDispatcher` — расширенный Protocol с
  ``dispatch(action, payload, context)``, ``get_metadata``,
  ``list_actions(transport)``, ``list_metadata(transport)``,
  ``register_middleware``.
* :class:`ActionMiddleware` — Protocol middleware-цепочки.

Backward compatibility: исходный :class:`ActionDispatcher` Protocol с
``dispatch(command: ActionCommandSchema)`` сохранён без изменений —
все существующие импортёры (``services/execution/invoker.py``,
``services/execution/action_dispatcher.py``) продолжают работать.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol, runtime_checkable

from src.core.types.invocation_command import ActionCommandSchema

__all__ = (
    "ActionDispatcher",
    "ActionError",
    "ActionGatewayDispatcher",
    "ActionMetadata",
    "ActionMiddleware",
    "ActionResult",
    "DispatchContext",
    "MiddlewareNextHandler",
    "SideEffect",
    "TransportName",
)


# ---------------------------------------------------------------------- #
# Type aliases                                                           #
# ---------------------------------------------------------------------- #

# Транспорт: "http", "grpc", "queue", "ws", "schedule", "internal", ...
# Свободная строка, чтобы не плодить enum для расширяемого набора.
TransportName = str

# Side-effect classification: "none" | "read" | "write" | "external".
# Свободная строка по тем же соображениям; реализация может использовать
# core.types.side_effect.SideEffect, если он там есть.
SideEffect = str


# ---------------------------------------------------------------------- #
# DTO: ActionError                                                        #
# ---------------------------------------------------------------------- #


@dataclass(slots=True)
class ActionError:
    """Структурированная ошибка action для унифицированного envelope.

    Attributes:
        code: Стабильный машиночитаемый код ошибки (например,
            ``"action.not_found"``, ``"validation.failed"``,
            ``"timeout"``, ``"rate_limited"``).
        message: Человекочитаемое сообщение.
        details: Дополнительные данные (поля валидации, traceback id и т.п.).
        recoverable: Разрешён ли retry на стороне клиента/middleware.
    """

    code: str
    message: str
    details: Mapping[str, Any] | None = None
    recoverable: bool = False


# ---------------------------------------------------------------------- #
# DTO: ActionResult                                                       #
# ---------------------------------------------------------------------- #


@dataclass(slots=True)
class ActionResult:
    """Унифицированный envelope результата action.

    Attributes:
        success: Признак успеха (True — ``data`` валидно, False —
            смотри ``error``).
        data: Полезная нагрузка ответа (результат вызова сервиса).
        error: Структура ошибки (заполняется при ``success=False``).
        metadata: Служебные метаданные (latency_ms, transport, retries,
            cached, и т.п.) — расширяемое поле без строгой схемы.
    """

    success: bool
    data: Any = None
    error: ActionError | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------- #
# DTO: DispatchContext                                                    #
# ---------------------------------------------------------------------- #


@dataclass(slots=True)
class DispatchContext:
    """Контекст вызова action (трассировка, мультиарендность, идемпотентность).

    Attributes:
        correlation_id: Сквозной ID запроса для логов и трассировки.
        tenant_id: Идентификатор арендатора (мультиарендность).
        user_id: Идентификатор пользователя-инициатора.
        idempotency_key: Ключ идемпотентности (если транспорт его передаёт).
        source: Транспорт-источник вызова (``"http"``, ``"grpc"``,
            ``"queue"``, ``"schedule"``, ``"internal"``, ...).
        trace_parent: W3C ``traceparent`` header value для distributed
            tracing.
        attributes: Расширяемая мапа произвольных атрибутов (request_path,
            client_ip, headers-allowlist, и т.п.).
    """

    correlation_id: str | None = None
    tenant_id: str | None = None
    user_id: str | None = None
    idempotency_key: str | None = None
    source: TransportName = "internal"
    trace_parent: str | None = None
    attributes: Mapping[str, Any] = field(default_factory=dict)


# ---------------------------------------------------------------------- #
# DTO: ActionMetadata                                                     #
# ---------------------------------------------------------------------- #


@dataclass(slots=True)
class ActionMetadata:
    """Расширенные метаданные зарегистрированного action.

    Совместимо с существующим :class:`ActionSpec`
    (``src/entrypoints/api/generator/specs.py``): ``input_model``,
    ``output_model`` и ``description`` отражают одноимённые поля
    ``ActionSpec``. Расширения (transports, side_effect, idempotent,
    permissions, rate_limit, timeout_ms, deprecated, since_version,
    error_types) — для Gateway-функциональности W14.

    Attributes:
        action: Уникальное имя action (например, ``"orders.create"``).
        description: Человекочитаемое описание.
        input_model: Pydantic-модель payload (опционально).
        output_model: Pydantic-модель ответа (опционально).
        transports: Список транспортов, через которые доступен action
            (``("http", "grpc", "queue")``).
        side_effect: Классификация побочного эффекта (``"none"``,
            ``"read"``, ``"write"``, ``"external"``).
        idempotent: Помечен ли action как идемпотентный (повторный
            вызов с тем же ``idempotency_key`` безопасен).
        permissions: Список требуемых разрешений (RBAC/ABAC scopes).
        rate_limit: Лимит вызовов в секунду на arendатора (None —
            без лимита).
        timeout_ms: Таймаут выполнения в миллисекундах (None — без
            таймаута).
        deprecated: Помечен ли action как устаревший.
        since_version: Версия API, в которой action появился.
        error_types: Список известных кодов ошибок, которые может
            вернуть action (для документации и контрактных тестов).
        tags: Произвольные теги для группировки/фильтрации.
    """

    action: str
    description: str | None = None

    # Schemas — типизированы как ``type[Any] | None`` чтобы не тянуть
    # ``pydantic`` в core/interfaces (это Protocol-уровень).
    input_model: type[Any] | None = None
    output_model: type[Any] | None = None

    transports: tuple[TransportName, ...] = ()
    side_effect: SideEffect = "none"
    idempotent: bool = False
    permissions: tuple[str, ...] = ()
    rate_limit: int | None = None
    timeout_ms: int | None = None
    deprecated: bool = False
    since_version: str | None = None
    error_types: tuple[str, ...] = ()
    tags: tuple[str, ...] = ()


# ---------------------------------------------------------------------- #
# Middleware                                                              #
# ---------------------------------------------------------------------- #

# Тип "следующего" обработчика в middleware-цепочке. Принимает уже
# подготовленный ``payload`` и ``context`` и возвращает :class:`ActionResult`.
MiddlewareNextHandler = Callable[
    [str, Mapping[str, Any], DispatchContext], Awaitable["ActionResult"]
]


@runtime_checkable
class ActionMiddleware(Protocol):
    """Protocol middleware-обёртки вокруг dispatch.

    Middleware вызывается в порядке регистрации; ответственен за вызов
    ``next_handler`` (или за короткое замыкание, например, при
    rate-limit/idempotency-cache hit).

    Пример::

        class LoggingMiddleware:
            async def __call__(self, action, payload, context, next_handler):
                logger.info("action.start", extra={"action": action})
                result = await next_handler(action, payload, context)
                logger.info("action.end", extra={"success": result.success})
                return result
    """

    async def __call__(
        self,
        action: str,
        payload: Mapping[str, Any],
        context: DispatchContext,
        next_handler: MiddlewareNextHandler,
    ) -> ActionResult:
        """Применить middleware и вернуть :class:`ActionResult`."""
        ...


# ---------------------------------------------------------------------- #
# Protocol: ActionDispatcher (legacy, W14.1)                              #
# ---------------------------------------------------------------------- #


@runtime_checkable
class ActionDispatcher(Protocol):
    """Главный диспетчер бизнес-команд (W14.1 Gateway, legacy contract).

    Контракт минимален и стабилен: транспорт-агностичный вызов action'а
    с произвольным payload. Все политики (idempotency, rate-limit,
    side-effect classification) применяются внутри реализации.

    .. note::
       Для нового Gateway-кода (W14.1.A+) использовать
       :class:`ActionGatewayDispatcher` — расширенный Protocol с
       :class:`DispatchContext` и :class:`ActionResult` envelope.
       Этот Protocol сохранён для обратной совместимости с
       существующими call sites (Invoker, DefaultActionDispatcher).
    """

    async def dispatch(self, command: ActionCommandSchema) -> Any:
        """Выполнить бизнес-команду и вернуть её результат."""
        ...

    def is_registered(self, action: str) -> bool:
        """Проверить наличие зарегистрированного обработчика."""
        ...

    def list_actions(self) -> tuple[str, ...]:
        """Список зарегистрированных action-имён (отсортированный)."""
        ...


# ---------------------------------------------------------------------- #
# Protocol: ActionGatewayDispatcher (W14.1.A, расширенный)                #
# ---------------------------------------------------------------------- #


@runtime_checkable
class ActionGatewayDispatcher(Protocol):
    """Расширенный диспетчер action для Gateway-функциональности (W14.1.A).

    Отличия от :class:`ActionDispatcher`:

    * принимает ``action``, ``payload``, ``context`` отдельно
      (без формирования :class:`ActionCommandSchema`);
    * возвращает унифицированный :class:`ActionResult` envelope;
    * предоставляет богатые метаданные (:class:`ActionMetadata`)
      и фильтрацию по транспортам;
    * поддерживает регистрацию middleware-цепочки.

    Реализация — Phase B (следующая фаза W14.1).
    """

    async def dispatch(
        self, action: str, payload: Mapping[str, Any], context: DispatchContext
    ) -> ActionResult:
        """Выполнить action и вернуть :class:`ActionResult` envelope."""
        ...

    def get_metadata(self, action: str) -> ActionMetadata | None:
        """Вернуть метаданные action или ``None``, если не зарегистрирован."""
        ...

    def list_actions(self, transport: TransportName | None = None) -> tuple[str, ...]:
        """Список action-имён, опционально отфильтрованный по транспорту.

        Args:
            transport: Если задан — возвращаются только action,
                поддерживающие этот транспорт (по
                :attr:`ActionMetadata.transports`).

        Returns:
            Отсортированный кортеж имён.
        """
        ...

    def list_metadata(
        self, transport: TransportName | None = None
    ) -> tuple[ActionMetadata, ...]:
        """Список метаданных, опционально отфильтрованный по транспорту."""
        ...

    def register_middleware(self, middleware: ActionMiddleware) -> None:
        """Зарегистрировать middleware в конце цепочки.

        Порядок регистрации = порядок вызова. Регистрация после первого
        ``dispatch`` допустима, но не обязана быть атомарной — реализация
        может потребовать "freeze" перед стартом приложения.
        """
        ...


# ---------------------------------------------------------------------- #
# Конструктор-хелпер для ActionResult                                     #
# ---------------------------------------------------------------------- #


def _seq_to_tuple(value: Sequence[str] | None) -> tuple[str, ...]:
    """Внутренний хелпер: превращает Sequence в tuple (для slot-friendly DTO).

    Используется реализациями, не самим Protocol.
    """
    if value is None:
        return ()
    return tuple(value)
