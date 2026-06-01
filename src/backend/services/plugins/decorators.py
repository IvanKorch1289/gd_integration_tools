"""Wave 4.3 — декораторы для repository-hooks плагинов.

Декораторы только **помечают** функцию метаданными — фактическая
регистрация происходит при вызове `BasePlugin.on_register_repositories`,
который сканирует методы плагина и переносит помеченные callback'и в
:class:`RepositoryHookRegistry`.

Такая отвязка позволяет писать плагины без зависимости от глобального
singleton — при загрузке `PluginLoader` вручную проводит регистрацию.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, ParamSpec, TypeVar

if TYPE_CHECKING:
    from collections.abc import Awaitable, Callable

__all__ = (
    "HOOK_ATTR",
    "OVERRIDE_ATTR",
    "collect_hook_methods",
    "collect_override_methods",
    "override_method",
    "repository_hook",
)

# Маркеры в `__dict__` помеченной функции.
HOOK_ATTR = "__plugin_hook__"
OVERRIDE_ATTR = "__plugin_override__"

P = ParamSpec("P")
R = TypeVar("R")


def repository_hook(
    repo_name: str, *, event: str
) -> Callable[[Callable[P, Awaitable[R]]], Callable[P, Awaitable[R]]]:
    """Помечает async-функцию как repository hook.

    Args:
        repo_name: Имя репозитория (`"orders"`, `"users"` и т.д.).
        event: Событие (`"before_create"`, `"after_query"`, ...).

    Пример:

    .. code-block:: python

        class AuditPlugin(BasePlugin):
            @repository_hook("orders", event="before_create")
            async def add_audit(self, repo, entity): ...
    """

    def decorator(fn: Callable[P, Awaitable[R]]) -> Callable[P, Awaitable[R]]:
        setattr(fn, HOOK_ATTR, (repo_name, event))
        return fn

    return decorator


def override_method(
    repo_name: str, method: str
) -> Callable[[Callable[P, Awaitable[R]]], Callable[P, Awaitable[R]]]:
    """Помечает async-функцию как override метода репозитория.

    Args:
        repo_name: Имя репозитория.
        method: Имя метода, который заменяется.
    """

    def decorator(fn: Callable[P, Awaitable[R]]) -> Callable[P, Awaitable[R]]:
        setattr(fn, OVERRIDE_ATTR, (repo_name, method))
        return fn

    return decorator


def collect_hook_methods(
    obj: object,
) -> tuple[tuple[str, str, Callable[..., Any]], ...]:
    """Собирает все методы объекта, помеченные `@repository_hook`.

    Returns:
        Tuple из `(repo_name, event, bound_method)`.
    """
    items: list[tuple[str, str, Callable[..., Any]]] = []
    for attr_name in dir(obj):
        if attr_name.startswith("__"):
            continue
        method = getattr(obj, attr_name, None)
        marker = getattr(method, HOOK_ATTR, None)
        if marker is None:
            continue
        repo_name, event = marker
        items.append((repo_name, event, method))
    return tuple(items)


def collect_override_methods(
    obj: object,
) -> tuple[tuple[str, str, Callable[..., Any]], ...]:
    """Собирает все методы, помеченные `@override_method`."""
    items: list[tuple[str, str, Callable[..., Any]]] = []
    for attr_name in dir(obj):
        if attr_name.startswith("__"):
            continue
        method = getattr(obj, attr_name, None)
        marker = getattr(method, OVERRIDE_ATTR, None)
        if marker is None:
            continue
        repo_name, method_name = marker
        items.append((repo_name, method_name, method))
    return tuple(items)
