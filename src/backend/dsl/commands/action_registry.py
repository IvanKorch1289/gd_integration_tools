"""Реестр action-обработчиков для DSL-маршрутов.

Предоставляет централизованное хранилище и dispatch
action-команд. Каждый action привязан к сервису и методу,
которые вызываются при поступлении ``ActionCommandSchema``.

Wave 14.1.B (Phase B) — расширение реестра под Gateway-функциональность:

* parallel storage метаданных (:class:`ActionMetadata`) рядом с
  существующим хранилищем :class:`ActionHandlerSpec`;
* регистрация middleware (:class:`ActionMiddleware`);
* новые методы :meth:`register_with_metadata`, :meth:`get_metadata`,
  :meth:`list_metadata`, :meth:`register_middleware`,
  :meth:`list_middleware`.

Backward compatibility:

* :meth:`register` и :meth:`register_many` сохраняют сигнатуры —
  при вызове автоматически создаётся минимальная
  :class:`ActionMetadata` (только ``action`` + ``input_model`` из
  ``payload_model``).
* :meth:`dispatch` не меняется (легаси контракт ``ActionDispatcher``).

ADR-0421 (авторизация на action-поверхности):

* ``ActionMetadata.permissions`` теперь **проверяется** перед вызовом
  обработчика (ранее поле только пропагировалось и нигде не читалось);
* action'ы с ``admin``-префиксом требуют ``role:admin``;
* отказ — fail-closed (:class:`ActionPermissionDeniedError`, HTTP 403)
  + audit-событие ``action.permission_denied``.
"""

import inspect
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel

from src.backend.core.errors import BaseError
from src.backend.core.interfaces.action_dispatcher import (
    ActionMetadata,
    ActionMiddleware,
)
from src.backend.core.logging import get_logger
from src.backend.schemas.invocation import ActionCommandSchema

__all__ = (
    "ADMIN_ACTION_PREFIXES",
    "ADMIN_PERMISSION",
    "ActionHandlerRegistry",
    "ActionHandlerSpec",
    "ActionPermissionDeniedError",
    "action_handler_registry",
    "enforce_action_permissions",
    "required_action_permissions",
    "resolve_action_permissions",
)

_logger = get_logger("dsl.commands.action_registry")

#: Permission, требуемая для action'ов с ``admin``-префиксом (ADR-0421).
ADMIN_PERMISSION: str = "role:admin"

#: Префиксы action-имён, трактуемых как административные (ADR-0421).
ADMIN_ACTION_PREFIXES: tuple[str, ...] = ("admin.", "admin_")

#: HTTP-статус отказа по правам. Константа вместо ``fastapi.status`` —
#: DSL-слой остаётся transport-agnostic (не тянет fastapi).
_FORBIDDEN_STATUS: int = 403


class ActionPermissionDeniedError(BaseError):
    """403 — principal не обладает permissions, требуемыми action'ом (ADR-0421).

    Attributes:
        action: Имя action'а, к которому отказано.
        required: Полный набор требуемых permissions.
        missing: Permissions, которых не хватает principal'у.
        principal: Идентификатор principal'а (пусто — anonymous).

    """

    def __init__(
        self,
        *,
        action: str,
        required: tuple[str, ...] = (),
        missing: tuple[str, ...] = (),
        principal: str = "",
    ) -> None:
        self.action = action
        self.required = required
        self.missing = missing
        self.principal = principal
        super().__init__(
            message=(
                f"Action '{action}' requires permissions {list(required)}; "
                f"principal '{principal or 'anonymous'}' lacks {list(missing)}"
            ),
            status_code=_FORBIDDEN_STATUS,
        )

    def to_detail(self) -> dict[str, Any]:
        """Безопасный ``detail`` для HTTP-ответа (без внутренних деталей).

        Returns:
            dict[str, Any]: Код ошибки, имя action'а и требуемые permissions.

        """
        return {
            "code": "action_permission_denied",
            "action": self.action,
            "required": list(self.required),
        }


def required_action_permissions(
    action: str, metadata: ActionMetadata | None = None
) -> tuple[str, ...]:
    """Возвращает требуемые permissions для action'а (ADR-0421).

    Приоритет:

    1. Явно объявленные ``ActionMetadata.permissions``;
    2. ``admin``-префикс имени action'а → ``role:admin``;
    3. иначе — пустой кортеж (action не требует прав).

    Args:
        action: Имя action'а.
        metadata: Метаданные action'а (если зарегистрированы).

    Returns:
        Кортеж требуемых permissions.

    """
    if metadata is not None and metadata.permissions:
        return tuple(metadata.permissions)
    if action.startswith(ADMIN_ACTION_PREFIXES):
        return (ADMIN_PERMISSION,)
    return ()


def resolve_action_permissions(auth: Any) -> tuple[str, ...]:
    """Собирает эффективные permissions principal'а для action-диспетчеризации.

    User-permissions берутся из ``AuthContext.metadata`` (``permissions``
    либо OAuth-``scope``), admin-роли — из ``metadata["admin_roles"]``.
    Каналы разные, а action'у нужно единое множество прав, поэтому
    наличие хотя бы одной admin-роли добавляет ``role:admin``.

    Args:
        auth: :class:`AuthContext` (или ``None``).

    Returns:
        Кортеж permission-строк (пустой — anonymous без прав).

    """
    from src.backend.core.auth.admin_roles import extract_admin_roles
    from src.backend.core.auth.auth_context_helpers import extract_user_permissions

    permissions = list(extract_user_permissions(auth))
    if extract_admin_roles(auth) and ADMIN_PERMISSION not in permissions:
        permissions.append(ADMIN_PERMISSION)
    return tuple(permissions)


async def enforce_action_permissions(
    *,
    action: str,
    required: tuple[str, ...],
    granted: tuple[str, ...],
    principal: str = "",
) -> None:
    """Проверяет права на action и эмитит audit-событие при отказе (ADR-0421).

    Семантика совпадает с ``permission_step`` из
    :class:`AuthorizationGateway`: требуются **все** permissions из
    ``required``. Пустой ``required`` — allow (backward compat).

    Args:
        action: Имя action'а.
        required: Требуемые permissions.
        granted: Фактические permissions principal'а.
        principal: Идентификатор principal'а (для логов/audit).

    Raises:
        ActionPermissionDeniedError: Если не хватает хотя бы одного
            требуемого permission (fail-closed).

    """
    if not required:
        return
    granted_set = set(granted)
    missing = tuple(p for p in required if p not in granted_set)
    if not missing:
        return
    await _emit_permission_denied(
        action=action, principal=principal, required=required, missing=missing
    )
    raise ActionPermissionDeniedError(
        action=action, required=required, missing=missing, principal=principal
    )


async def _emit_permission_denied(
    *, action: str, principal: str, required: tuple[str, ...], missing: tuple[str, ...]
) -> None:
    """Эмитит audit-событие ``action.permission_denied`` (best-effort)."""
    _logger.warning(
        "action_permission_denied action=%s principal=%s missing=%s",
        action,
        principal or "anonymous",
        list(missing),
    )
    try:
        from src.backend.core.audit.facade.audit_service import (
            get_unified_audit_service,
        )

        await get_unified_audit_service().emit(
            event="action.permission_denied",
            actor=principal or "anonymous",
            resource=f"action/{action}",
            action="dispatch",
            outcome="denied",
            severity="warning",
            details={"required": list(required), "missing": list(missing)},
        )
    except Exception as exc:  # noqa: BLE001 — audit не должен ломать отказ
        _logger.debug("audit_emit_failed action=%s error=%s", action, exc)


@dataclass(slots=True)
class ActionHandlerSpec:
    """Спецификация одного action-обработчика.

    Attrs:
        action: Уникальное имя действия (например,
            ``orders.create_skb_order``).
        service_getter: Фабрика, возвращающая экземпляр сервиса.
        service_method: Имя метода сервиса для вызова.
        payload_model: Pydantic-модель для валидации payload.
            Если указана, ``payload`` из команды будет
            провалидирован и развёрнут в kwargs.
    """

    action: str
    service_getter: Callable[[], Any]
    service_method: str
    payload_model: type[BaseModel] | None = None


class ActionHandlerRegistry:
    """Реестр и диспетчер action-обработчиков.

    Хранит ``action_name`` -> ``ActionHandlerSpec`` и предоставляет
    единый ``dispatch()`` для вызова из любого entrypoint
    (HTTP, stream, gRPC, DSL pipeline).

    Wave 14.1.B: дополнительно хранит ``action_name`` ->
    :class:`ActionMetadata` (parallel storage) и упорядоченный
    список middleware. Метаданные используются Gateway-слоем
    (W14.1.A контракт :class:`ActionGatewayDispatcher`) и developer
    portal'ом для автоматической документации.
    """

    def __init__(self) -> None:
        """Инициализирует процессор."""
        self._handlers: dict[str, ActionHandlerSpec] = {}
        self._metadata: dict[str, ActionMetadata] = {}
        self._middleware: list[ActionMiddleware] = []

    def register(
        self,
        *,
        action: str,
        service_getter: Callable[[], Any],
        service_method: str,
        payload_model: type[BaseModel] | None = None,
    ) -> None:
        """Регистрирует один action-обработчик.

        Если метаданные ``action`` ещё не зарегистрированы — создаётся
        минимальная :class:`ActionMetadata` (с ``input_model =
        payload_model``). Уже сохранённые метаданные не перезаписываются —
        это позволяет сначала вызвать :meth:`register_with_metadata` с
        полной декларацией, а затем (например, из
        ``setup.register_action_handlers``) повторно вызвать
        :meth:`register` для привязки к сервису без потери метаданных.

        Args:
            action: Уникальное имя действия.
            service_getter: Фабрика сервиса.
            service_method: Имя метода сервиса.
            payload_model: Модель валидации payload.

        """
        self._handlers[action] = ActionHandlerSpec(
            action=action,
            service_getter=service_getter,
            service_method=service_method,
            payload_model=payload_model,
        )
        if action not in self._metadata:
            self._metadata[action] = ActionMetadata(
                action=action, input_model=payload_model
            )

    def register_many(self, specs: list[ActionHandlerSpec]) -> None:
        """Регистрирует несколько action-обработчиков.

        Минимальные метаданные создаются по тем же правилам, что и
        в :meth:`register`.

        Args:
            specs: Список спецификаций для регистрации.

        """
        for spec in specs:
            self._handlers[spec.action] = spec
            if spec.action not in self._metadata:
                self._metadata[spec.action] = ActionMetadata(
                    action=spec.action, input_model=spec.payload_model
                )

    def register_with_metadata(
        self,
        *,
        action: str,
        handler: Callable[..., Any] | ActionHandlerSpec | None,
        metadata: ActionMetadata,
    ) -> None:
        """Регистрирует action вместе с расширенной :class:`ActionMetadata`.

        Используется Gateway-слоем и адаптерами (например,
        ``ActionRouterBuilder``) для регистрации action с полной
        декларацией метаданных.

        Args:
            action: Уникальное имя действия.
            handler: Один из вариантов:

                * :class:`ActionHandlerSpec` — будет сохранён в
                  ``self._handlers`` как обычно;
                * любой ``Callable`` — будет обёрнут как handler
                  без привязки к сервису (используется для
                  metadata-only регистраций, когда сам диспатч
                  обрабатывается транспортом, например,
                  FastAPI-эндпоинтом);
                * ``None`` — регистрация только метаданных
                  (handler уже зарегистрирован отдельно или
                  будет зарегистрирован позже через
                  :meth:`register`).

        Raises:
            ValueError: Если ``metadata.action`` не совпадает с
                переданным ``action``.

        """
        if metadata.action != action:
            raise ValueError(
                f"metadata.action={metadata.action!r} != action={action!r}"
            )

        # Cycle 133: atomic re-registration conflict check (BEFORE any
        # mutation — ensures ``test_conflict_does_not_mutate_registry``
        # passes with state intact on raise).
        #
        # Three conflict paths:
        # 1. New handler.payload_model != new metadata.input_model
        #    (intra-call consistency — see test_conflicting_handler_*).
        # 2. Existing handler.payload_model != new metadata.input_model
        #    (re-registration with different schemas).
        # 3. Existing metadata.input_model != new metadata.input_model
        #    (metadata-only re-registration).
        if metadata.input_model is not None:
            new_handler_payload_model = (
                handler.payload_model
                if isinstance(handler, ActionHandlerSpec)
                else None
            )
            if (
                new_handler_payload_model is not None
                and new_handler_payload_model is not metadata.input_model
            ):
                raise ValueError(
                    "Atomic re-registration conflict: "
                    f"new handler.payload_model={new_handler_payload_model!r} "
                    f"!= new metadata.input_model={metadata.input_model!r} "
                    f"for action={action!r}"
                )
            existing_handler = self._handlers.get(action)
            if (
                existing_handler is not None
                and existing_handler.payload_model is not None
                and existing_handler.payload_model is not metadata.input_model
            ):
                raise ValueError(
                    "Atomic re-registration conflict: "
                    f"existing handler.payload_model={existing_handler.payload_model!r} "
                    f"!= metadata.input_model={metadata.input_model!r} "
                    f"for action={action!r}"
                )
            existing_metadata = self._metadata.get(action)
            if (
                existing_metadata is not None
                and existing_metadata.input_model is not None
                and existing_metadata.input_model is not metadata.input_model
            ):
                raise ValueError(
                    "Atomic re-registration conflict: "
                    f"existing metadata.input_model={existing_metadata.input_model!r} "
                    f"!= new metadata.input_model={metadata.input_model!r} "
                    f"for action={action!r}"
                )

        if isinstance(handler, ActionHandlerSpec):
            self._handlers[action] = handler
        elif handler is not None and not isinstance(handler, ActionHandlerSpec):
            # Сохраняем callable как обёртку: service_getter возвращает
            # объект-носитель, у которого ``__call__`` — наш handler.
            # Однако чаще всего сюда приходит handler=None (metadata-only)
            # либо ActionHandlerSpec. Этот ветке оставляем для будущих
            # сценариев — не пытаемся синтезировать сервис «на лету».
            raise TypeError(
                "handler must be ActionHandlerSpec or None; "
                f"got {type(handler).__name__}"
            )

        self._metadata[action] = metadata

    def get_metadata(self, action: str) -> ActionMetadata | None:
        """Возвращает метаданные action.

        Args:
            action: Имя действия.

        Returns:
            :class:`ActionMetadata` или ``None``, если action не
            зарегистрирован.

        """
        return self._metadata.get(action)

    def list_metadata(self, transport: str | None = None) -> tuple[ActionMetadata, ...]:
        """Возвращает список метаданных всех зарегистрированных actions.

        Args:
            transport: Если задан — возвращаются только метаданные,
                чей ``transports`` содержит указанный транспорт.
                Если ``None`` — возвращаются все.

        Returns:
            Кортеж :class:`ActionMetadata`, отсортированный по
            ``action``.

        """
        items = sorted(self._metadata.values(), key=lambda m: m.action)
        if transport is None:
            return tuple(items)
        return tuple(m for m in items if transport in m.transports)

    def register_middleware(self, middleware: ActionMiddleware) -> None:
        """Регистрирует middleware в конце цепочки.

        Порядок регистрации = порядок вызова. Middleware вызывается
        Gateway-диспетчером (Phase C), реестр лишь хранит цепочку.

        Args:
            middleware: Реализация :class:`ActionMiddleware`.

        """
        self._middleware.append(middleware)

    def list_middleware(self) -> tuple[ActionMiddleware, ...]:
        """Возвращает кортеж зарегистрированных middleware в порядке регистрации."""
        return tuple(self._middleware)

    def required_permissions(self, action: str) -> tuple[str, ...]:
        """Требуемые permissions для action'а (ADR-0421).

        Args:
            action: Имя action'а.

        Returns:
            Кортеж требуемых permissions (пустой — action не требует прав).

        """
        return required_action_permissions(action, self._metadata.get(action))

    def missing_permissions(
        self, action: str, granted: tuple[str, ...]
    ) -> tuple[str, ...]:
        """Permissions, которых не хватает principal'у для action'а (ADR-0421).

        Args:
            action: Имя action'а.
            granted: Фактические permissions principal'а.

        Returns:
            Кортеж недостающих permissions (пустой — доступ разрешён).

        """
        granted_set = set(granted)
        return tuple(
            p for p in self.required_permissions(action) if p not in granted_set
        )

    async def _enforce_permissions(self, command: ActionCommandSchema) -> None:
        """ADR-0421: fail-closed проверка прав перед вызовом обработчика."""
        required = self.required_permissions(command.action)
        if not required:
            return
        await enforce_action_permissions(
            action=command.action,
            required=required,
            granted=tuple(command.meta.permissions or ()),
            principal=command.meta.principal or "",
        )

    async def dispatch(self, command: ActionCommandSchema) -> Any:
        """Выполняет action-команду.

        Находит обработчик по ``command.action``, **проверяет права**
        (ADR-0421), валидирует payload (если указана ``payload_model``),
        вызывает метод сервиса и возвращает результат.

        Args:
            command: Команда для выполнения.

        Returns:
            Результат вызова метода сервиса.

        Raises:
            KeyError: Если action не зарегистрирован.
            ValidationError: Если payload не прошёл валидацию.
            ActionPermissionDeniedError: Если principal не обладает
                требуемыми permissions (fail-closed, HTTP 403).

        """
        spec = self._handlers[command.action]
        await self._enforce_permissions(command)

        service = spec.service_getter()
        method = getattr(service, spec.service_method)

        if spec.payload_model is not None:
            # Cycle 132: validate even on empty payload (previously
            # ``and command.payload`` skipped validation on falsy
            # dict, which masked required-field violations on
            # empty commands).
            validated = spec.payload_model.model_validate(command.payload)
            kwargs = {
                field_name: getattr(validated, field_name)
                for field_name in validated.model_fields
                if getattr(validated, field_name) is not None
            }
        else:
            kwargs = command.payload or {}

        result = method(**kwargs)
        if inspect.isawaitable(result):
            result = await result

        return result

    def is_registered(self, action: str) -> bool:
        """Проверяет наличие action-обработчика.

        Args:
            action: Имя действия.

        Returns:
            ``True`` если обработчик зарегистрирован.

        """
        return action in self._handlers

    def list_actions(self) -> tuple[str, ...]:
        """Возвращает список зарегистрированных action-имён.

        Returns:
            Отсортированный кортеж имён.

        """
        return tuple(sorted(self._handlers.keys()))

    def clear(self) -> None:
        """Очищает реестр обработчиков, метаданные и middleware."""
        self._handlers.clear()
        self._metadata.clear()
        self._middleware.clear()


action_handler_registry = ActionHandlerRegistry()
