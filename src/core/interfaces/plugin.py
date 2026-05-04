"""Wave 4 (Roadmap V10) — контракт плагина и lifecycle-хуки.

Реализует Open-Closed принцип (ADR-011, V10 #3): ядро (`src/dsl/`,
`src/core/`) закрыто, расширения добавляются через `BasePlugin`-наследников
в дистрибутивах с `entry_points(group="gd_integration_tools.plugins")`.

Архитектурные ограничения:

* Модуль живёт в `core/` → не импортирует `infrastructure/`, `services/`,
  `entrypoints/`. Все зависимости описаны как Protocol.
* Lifecycle-хуки async-only (DI-контейнер async, FastAPI startup/shutdown
  тоже async).
* Каждый хук получает либо `PluginContext`, либо узкий registry-Protocol —
  плагин не имеет прямого доступа к app.state, чтобы не плодить
  скрытых зависимостей.

DoD: пример плагина (`plugins/example_plugin/`) добавляет endpoint и
override репозитория без правок ядра.
"""

from __future__ import annotations

from abc import ABC
from typing import TYPE_CHECKING, Any, Protocol, runtime_checkable

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

__all__ = (
    "ActionRegistryProtocol",
    "BasePlugin",
    "PluginContext",
    "PluginInfo",
    "ProcessorRegistryProtocol",
    "RepositoryRegistryProtocol",
)


@runtime_checkable
class ActionRegistryProtocol(Protocol):
    """Минимальный контракт реестра actions для плагина.

    Полная реализация — `services/actions/registry.py::ActionHandlerRegistry`.
    Здесь описана только поверхность, нужная плагинам.
    """

    def register(
        self,
        action_id: str,
        handler: Callable[..., Awaitable[Any]],
        *,
        spec: Any | None = None,
    ) -> None:
        """Зарегистрировать handler под `action_id`."""
        ...


@runtime_checkable
class RepositoryRegistryProtocol(Protocol):
    """Контракт реестра репозиториев + hook/override механика.

    Реализуется в `services/repositories/registry.py` (Wave 4.3).
    """

    def register_hook(
        self, repo_name: str, event: str, callback: Callable[..., Awaitable[Any]]
    ) -> None:
        """Зарегистрировать hook на событие репозитория.

        Args:
            repo_name: Имя репозитория (`"orders"`, `"users"` и т.д.).
            event: Событие (`"before_create"`, `"after_query"`, ...).
            callback: Async-callable, получает `(repo, *args, **kwargs)`.
        """
        ...

    def override_method(
        self, repo_name: str, method: str, replacement: Callable[..., Awaitable[Any]]
    ) -> None:
        """Подменить метод репозитория целиком."""
        ...


@runtime_checkable
class ProcessorRegistryProtocol(Protocol):
    """Контракт реестра DSL-процессоров (см. dsl.engine.plugin_registry)."""

    def register_class(self, name: str, cls: type) -> None:
        """Зарегистрировать класс процессора по имени."""
        ...


class PluginContext:
    """Контекст, передаваемый плагину в `on_load`.

    Содержит ссылки на узкие registry-Protocol, через которые плагин
    выполняет регистрации. Ничего больше плагину знать не нужно — это
    защищает от case-by-case зависимостей.

    Attributes:
        plugin_name: Имя плагина (из manifest).
        actions: Реестр actions (handler-регистрация).
        repositories: Реестр репозиториев (hooks + override).
        processors: Реестр DSL-процессоров.
        config: Произвольный dict с настройками плагина (из plugin.yaml).
    """

    __slots__ = ("actions", "config", "plugin_name", "processors", "repositories")

    def __init__(
        self,
        *,
        plugin_name: str,
        actions: ActionRegistryProtocol,
        repositories: RepositoryRegistryProtocol,
        processors: ProcessorRegistryProtocol,
        config: dict[str, Any] | None = None,
    ) -> None:
        """Инициализирует контекст плагина."""
        self.plugin_name = plugin_name
        self.actions = actions
        self.repositories = repositories
        self.processors = processors
        self.config: dict[str, Any] = config or {}


class PluginInfo:
    """Метаданные загруженного плагина (для админ-эндпоинта)."""

    __slots__ = ("name", "python_requires", "source", "version")

    def __init__(
        self,
        *,
        name: str,
        version: str,
        python_requires: str | None = None,
        source: str = "entry_point",
    ) -> None:
        """Инициализирует метаданные плагина."""
        self.name = name
        self.version = version
        self.python_requires = python_requires
        self.source = source

    def to_dict(self) -> dict[str, Any]:
        """Сериализация для `/admin/plugins`."""
        return {
            "name": self.name,
            "version": self.version,
            "python_requires": self.python_requires,
            "source": self.source,
        }


class BasePlugin(ABC):
    """Базовый класс плагина (Wave 4 / Roadmap V10 #3).

    Плагин наследует `BasePlugin`, переопределяет нужные lifecycle-хуки
    (все опциональные, дефолт — no-op) и регистрируется через
    `entry_points(group="gd_integration_tools.plugins")` своего дистрибутива.

    Жизненный цикл (порядок вызова `PluginLoader`):

    1. `on_load(ctx)` — общая инициализация, доступ к контексту.
    2. `on_register_actions(registry)` — регистрация HTTP/CLI/RPC-actions.
    3. `on_register_repositories(registry)` — hooks/override репозиториев.
    4. `on_register_processors(registry)` — кастомные DSL-процессоры.
    5. (runtime — плагин обслуживает запросы)
    6. `on_shutdown()` — graceful очистка ресурсов.

    Пример:

    .. code-block:: python

        class MyPlugin(BasePlugin):
            name = "my_plugin"
            version = "1.0.0"

            async def on_load(self, ctx: PluginContext) -> None:
                self._db = await connect_my_storage(ctx.config["dsn"])

            async def on_register_actions(
                self, registry: ActionRegistryProtocol
            ) -> None:
                registry.register("my.echo", self._echo_handler)

            async def on_shutdown(self) -> None:
                await self._db.close()
    """

    name: str = ""
    version: str = "0.0.0"

    async def on_load(self, ctx: PluginContext) -> None:  # noqa: B027 — намеренно пустой default
        """Вызывается единожды при загрузке плагина.

        Default: no-op. Плагин может закэшировать `ctx`, читать `config`,
        инициализировать соединения и т.д.
        """

    async def on_register_actions(  # noqa: B027
        self, registry: ActionRegistryProtocol
    ) -> None:
        """Регистрация HTTP/CLI/RPC actions через `registry.register(...)`."""

    async def on_register_repositories(  # noqa: B027
        self, registry: RepositoryRegistryProtocol
    ) -> None:
        """Регистрация repository-hooks и override-методов."""

    async def on_register_processors(  # noqa: B027
        self, registry: ProcessorRegistryProtocol
    ) -> None:
        """Регистрация кастомных DSL-процессоров (`BaseProcessor`-наследников)."""

    async def on_shutdown(self) -> None:  # noqa: B027
        """Graceful shutdown: закрытие соединений, отмена тасков и т.д."""

    def info(self) -> PluginInfo:
        """Метаданные плагина для админ-эндпоинта."""
        return PluginInfo(name=self.name, version=self.version)
