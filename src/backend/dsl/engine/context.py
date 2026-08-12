import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from src.backend.dsl.commands.registry import (
    ActionHandlerRegistry,
    action_handler_registry,
)

if TYPE_CHECKING:
    # Только для type-checker; реальный импорт ленивый, чтобы не
    # создавать циклическую зависимость ``core.auth → dsl``.
    pass

__all__ = ("ExecutionContext",)


@dataclass(slots=True)
class ExecutionContext:
    """Контекст выполнения DSL-маршрута.

    Хранит зависимости и shared-state, которые нужны процессорам во время
    обработки Exchange, но не должны попадать в payload сообщения.

    Attributes:
        action_registry: Реестр action-команд.
        logger: Опциональный logger для трассировки выполнения.
        state: Общий изменяемый словарь для обмена данными между процессорами.
        route_id: Идентификатор текущего маршрута (для логирования).
        principal: K3 S19 W3 / Sprint 1 — идентификатор текущего principal'а
            (user / plugin / service). Используется
            :func:`check_route_permission` для enforcement
            ``route.toml [security] requires_permission`` (через
            :class:`AuthorizationGateway`). По умолчанию пустая строка —
            ``check_route_permission`` трактует как ``"anonymous"``
            (fail-closed при включённом флаге).
        permissions: K3 S19 W3 / Sprint 1 — кортеж permissions-principal'а
            (формат ``"role:..."`` или ``"scope:..."``). По умолчанию
            пустой кортеж; должен выставляться auth-middleware'ю до
            вызова :meth:`DslService.dispatch`. Используется для
            route-wide permission enforcement.

    """

    action_registry: ActionHandlerRegistry = action_handler_registry
    logger: logging.Logger | None = None
    route_id: str = ""
    state: dict[str, Any] = field(default_factory=dict)
    principal: str = ""  # K3 S19 W3
    permissions: tuple[str, ...] = ()  # K3 S19 W3

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

        Sprint 1 / K3 S19 W3: проброс ``principal/permissions`` из
        middleware auth в DSL pipeline для route-wide permission
        enforcement.

        Args:
            auth: :class:`AuthContext` (или duck-typed ``metadata: dict``).
                ``None`` допустим — вернётся ``ExecutionContext`` с
                пустым principal и пустым permissions (fail-closed).
            route_id: Идентификатор текущего маршрута.
            logger: Опциональный logger.
            state: Опциональный shared state.

        Returns:
            ``ExecutionContext`` с заполненными ``principal`` и ``permissions``.

        """
        # Ленивый импорт — иначе цикл ``core.auth → dsl → core.auth``.
        from src.backend.core.auth.auth_context_helpers import extract_user_permissions

        principal = ""
        permissions: tuple[str, ...] = ()
        if auth is not None:
            raw_principal = getattr(auth, "principal", "")
            if isinstance(raw_principal, str):
                principal = raw_principal
            permissions = extract_user_permissions(auth)
        return cls(
            route_id=route_id,
            logger=logger,
            state=state if state is not None else {},
            principal=principal,
            permissions=permissions,
        )

    def get(self, key: str, default: Any = None) -> Any:
        """Возвращает значение из shared-state.

        Args:
            key: Ключ.
            default: Значение по умолчанию.

        Returns:
            Any: Найденное значение или default.

        """
        return self.state.get(key, default)

    def set(self, key: str, value: Any) -> None:
        """Сохраняет значение в shared-state.

        Args:
            key: Ключ.
            value: Значение.

        """
        self.state[key] = value
