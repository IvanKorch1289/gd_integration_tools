"""Wave 4 — реестры/адаптеры для plugin-системы.

Содержит:

* :class:`RepositoryHookRegistry` — централизованный реестр `(repo, event)`
  hooks + override-методов. Lookup амортизированно O(1) (`dict[(repo, event)]`).
* :class:`ActionRegistryAdapter` — обёртка над
  :class:`src.dsl.commands.action_registry.ActionHandlerRegistry`,
  чтобы плагины не зависели от внутренней `ActionHandlerSpec`-сигнатуры.
* :class:`ProcessorRegistryAdapter` — обёртка над
  :class:`src.dsl.engine.plugin_registry.ProcessorPluginRegistry`.

Зачем адаптеры: плагины зависят только от Protocol из
`core/interfaces/plugin.py`. Внутренние API (`ActionHandlerSpec`,
`ProcessorPluginRegistry`) могут меняться без слома плагинов.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from src.core.di import app_state_singleton

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable, Iterable

    from src.dsl.commands.action_registry import ActionHandlerRegistry
    from src.dsl.engine.plugin_registry import ProcessorPluginRegistry

__all__ = (
    "ActionRegistryAdapter",
    "ProcessorRegistryAdapter",
    "RepositoryHookRegistry",
    "get_repository_hook_registry",
)

logger = logging.getLogger("services.plugins")

# Стандартные события репозитория (V10 #3 + ADR-011).
KNOWN_REPO_EVENTS = frozenset(
    {
        "before_create",
        "after_create",
        "before_update",
        "after_update",
        "before_delete",
        "after_delete",
        "before_query",
        "after_query",
    }
)


class RepositoryHookRegistry:
    """Реестр repository hooks + override-методов.

    Hooks хранятся как `dict[(repo, event)] -> list[callback]` — порядок
    регистрации сохраняется (FIFO). `override_method` хранится как
    `dict[(repo, method)] -> callback` (последний победил).

    Все callbacks — async-callable. Sync-callbacks не поддерживаются
    (см. правило `refactoring.md`: async-only в БД-слое).
    """

    def __init__(self) -> None:
        """Инициализирует пустой реестр."""
        self._hooks: dict[tuple[str, str], list[Callable[..., Awaitable[Any]]]] = {}
        self._overrides: dict[tuple[str, str], Callable[..., Awaitable[Any]]] = {}

    def register_hook(
        self,
        repo_name: str,
        event: str,
        callback: Callable[..., Awaitable[Any]],
    ) -> None:
        """Регистрирует hook на событие репозитория.

        Args:
            repo_name: Имя репозитория (`"orders"`, `"users"` и т.д.).
            event: Стандартное событие из ``KNOWN_REPO_EVENTS`` либо
                кастомное (для нестандартных репозиториев).
            callback: Async-callable, вызывается как
                ``await callback(repo, *args, **kwargs)``.
        """
        if event not in KNOWN_REPO_EVENTS:
            logger.warning(
                "Repository hook on non-standard event: %s.%s — "
                "разрешено, но не покрыто стандартной диспатч-логикой",
                repo_name,
                event,
            )
        key = (repo_name, event)
        self._hooks.setdefault(key, []).append(callback)
        logger.info(
            "Repository hook registered: %s.%s → %s",
            repo_name,
            event,
            getattr(callback, "__qualname__", repr(callback)),
        )

    def override_method(
        self,
        repo_name: str,
        method: str,
        replacement: Callable[..., Awaitable[Any]],
    ) -> None:
        """Подменяет метод репозитория целиком.

        При повторном override — последний регистрируется, предыдущий
        логируется как warning (ADR-011: явное предпочтение последнего).
        """
        key = (repo_name, method)
        if key in self._overrides:
            previous = self._overrides[key]
            logger.warning(
                "Repository override conflict: %s.%s — %s replaces %s",
                repo_name,
                method,
                getattr(replacement, "__qualname__", repr(replacement)),
                getattr(previous, "__qualname__", repr(previous)),
            )
        self._overrides[key] = replacement
        logger.info(
            "Repository method override: %s.%s → %s",
            repo_name,
            method,
            getattr(replacement, "__qualname__", repr(replacement)),
        )

    def hooks_for(
        self, repo_name: str, event: str
    ) -> Iterable[Callable[..., Awaitable[Any]]]:
        """Возвращает список зарегистрированных hooks для `(repo, event)`."""
        return tuple(self._hooks.get((repo_name, event), ()))

    def get_override(
        self, repo_name: str, method: str
    ) -> Callable[..., Awaitable[Any]] | None:
        """Возвращает override метода либо None."""
        return self._overrides.get((repo_name, method))

    async def dispatch(
        self,
        repo_name: str,
        event: str,
        repo: Any,
        *args: Any,
        **kwargs: Any,
    ) -> None:
        """Вызвать все hooks для `(repo, event)` последовательно.

        Ошибки одного hook'а не блокируют остальные — логируются и
        продолжается обработка (graceful degradation, ADR-036 принцип).
        """
        for callback in self.hooks_for(repo_name, event):
            try:
                await callback(repo, *args, **kwargs)
            except Exception:
                logger.exception(
                    "Repository hook failed: %s.%s callback=%s",
                    repo_name,
                    event,
                    getattr(callback, "__qualname__", repr(callback)),
                )

    def stats(self) -> dict[str, int]:
        """Сводка для админ-эндпоинта."""
        return {
            "hooks": sum(len(v) for v in self._hooks.values()),
            "hook_keys": len(self._hooks),
            "overrides": len(self._overrides),
        }

    def reset(self) -> None:
        """Очистить реестр (для тестов / повторного `create_app`)."""
        self._hooks.clear()
        self._overrides.clear()


@app_state_singleton("repository_hook_registry", factory=RepositoryHookRegistry)
def get_repository_hook_registry() -> RepositoryHookRegistry:
    """Singleton-accessor `RepositoryHookRegistry` через `app.state`."""
    raise RuntimeError("unreachable — фабрика создаёт пустой реестр")


class ActionRegistryAdapter:
    """Тонкий адаптер `ActionRegistryProtocol` → `ActionHandlerRegistry`.

    Преобразует `(action_id, handler)` плагина в формат
    `register_with_metadata(action=..., handler=callable, metadata=...)`,
    минуя `ActionHandlerSpec` (плагины не должны знать про сервис-геттеры).
    """

    def __init__(self, target: ActionHandlerRegistry) -> None:
        """Создаёт адаптер поверх существующего реестра."""
        self._target = target

    def register(
        self,
        action_id: str,
        handler: Callable[..., Awaitable[Any]],
        *,
        spec: Any | None = None,
    ) -> None:
        """Регистрирует action: handler оборачивается в `ActionHandlerSpec`.

        Внутренний `ActionHandlerRegistry` хранит спецификацию в виде
        `(service_getter, service_method)`. Чтобы плагины не знали об этом
        контракте, callable плагина оборачивается в объект-носитель
        `_PluginCallableCarrier(handler).call(**kwargs)`.

        Если `spec` предоставлен (`ActionMetadata`) — используется как есть,
        иначе создаётся минимальный stub.
        """
        from src.core.interfaces.action_dispatcher import ActionMetadata
        from src.dsl.commands.action_registry import ActionHandlerSpec

        metadata = spec if isinstance(spec, ActionMetadata) else ActionMetadata(
            action=action_id, input_model=None
        )
        carrier = _PluginCallableCarrier(handler)

        def _carrier_getter() -> _PluginCallableCarrier:
            return carrier

        handler_spec = ActionHandlerSpec(
            action=action_id,
            service_getter=_carrier_getter,
            service_method="call",
            payload_model=None,
        )
        self._target.register_with_metadata(
            action=action_id, handler=handler_spec, metadata=metadata
        )
        logger.info("Plugin registered action: %s", action_id)


class _PluginCallableCarrier:
    """Носитель async-callable для совместимости с `ActionHandlerSpec`.

    `ActionHandlerSpec` ожидает `service_getter().service_method(**kwargs)`.
    Плагин предоставляет голый callable — носитель приводит его к этому
    интерфейсу через `.call(**kwargs)`.
    """

    __slots__ = ("_fn",)

    def __init__(self, fn: Callable[..., Awaitable[Any]]) -> None:
        """Сохраняет callable плагина."""
        self._fn = fn

    async def call(self, **kwargs: Any) -> Any:
        """Делегирует вызов в исходный callable."""
        return await self._fn(**kwargs)


class ProcessorRegistryAdapter:
    """Тонкий адаптер `ProcessorRegistryProtocol` → `ProcessorPluginRegistry`."""

    def __init__(self, target: ProcessorPluginRegistry) -> None:
        """Создаёт адаптер поверх существующего реестра процессоров."""
        self._target = target

    def register_class(self, name: str, cls: type) -> None:
        """Регистрирует класс DSL-процессора."""
        from src.dsl.engine.processors import BaseProcessor

        if not (isinstance(cls, type) and issubclass(cls, BaseProcessor)):
            raise TypeError(
                f"{cls!r} is not a BaseProcessor subclass — отказ в регистрации"
            )
        self._target.register_class(name, cls)
        logger.info("Plugin registered DSL processor: %s → %s", name, cls.__name__)
