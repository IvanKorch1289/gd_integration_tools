import logging
from dataclasses import dataclass, field
from typing import Any

from src.backend.dsl.commands.registry import (
    ActionHandlerRegistry,
    action_handler_registry,
)

__all__ = ("ExecutionContext",)


@dataclass(slots=True)
class ExecutionContext:
    """
    Контекст выполнения DSL-маршрута.

    Хранит зависимости и shared-state, которые нужны процессорам во время
    обработки Exchange, но не должны попадать в payload сообщения.

    Attributes:
        action_registry: Реестр action-команд.
        logger: Опциональный logger для трассировки выполнения.
        state: Общий изменяемый словарь для обмена данными между процессорами.
        route_id: Идентификатор текущего маршрута (для логирования).
        principal: Sprint 1 — идентификатор аутентифицированного пользователя
            (для route-wide permission enforcement через :class:`AuthorizationGateway`).
        permissions: Sprint 1 — кортеж строк-permissions principal'а для
            авторизации.
    """

    action_registry: ActionHandlerRegistry = action_handler_registry
    logger: logging.Logger | None = None
    route_id: str = ""
    state: dict[str, Any] = field(default_factory=dict)
    principal: str = ""
    permissions: tuple[str, ...] = ()

    @classmethod
    def from_auth(
        cls,
        auth: Any,
        *,
        route_id: str = "",
        logger: logging.Logger | None = None,
        state: dict[str, Any] | None = None,
    ) -> ExecutionContext:
        """Собирает ``ExecutionContext`` из ``AuthContext``.

        Sprint 1: проброс ``principal/permissions`` из middleware auth
        в DSL pipeline для route-wide permission enforcement.

        Args:
            auth: :class:`AuthContext` (или duck-typed ``metadata: dict``).
            route_id: Идентификатор текущего маршрута.
            logger: Опциональный logger.
            state: Опциональный shared state.

        Returns:
            ``ExecutionContext`` с заполненными ``principal`` и ``permissions``.
        """
        from src.backend.core.auth.auth_context_helpers import (
            extract_user_permissions,
        )

        principal: str = ""
        permissions: tuple[str, ...] = ()
        if auth is not None:
            principal = getattr(auth, "principal", "") or ""
            permissions = extract_user_permissions(auth)
        return cls(
            route_id=route_id,
            logger=logger,
            state=state if state is not None else {},
            principal=principal,
            permissions=permissions,
        )

    def get(self, key: str, default: Any = None) -> Any:
        """
        Возвращает значение из shared-state.

        Args:
            key: Ключ.
            default: Значение по умолчанию.

        Returns:
            Any: Найденное значение или default.
        """
        return self.state.get(key, default)

    def set(self, key: str, value: Any) -> None:
        """
        Сохраняет значение в shared-state.

        Args:
            key: Ключ.
            value: Значение.
        """
        self.state[key] = value
