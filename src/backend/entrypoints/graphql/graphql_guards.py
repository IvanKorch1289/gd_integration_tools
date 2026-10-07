"""GraphQL guards: depth-limit + introspection policy (P0, audit a2bd6f294).

- QueryDepthLimiter(12) — защита от вложенных depth-атак.
- Introspection: разрешена только в environment="development"; в
  staging/prod — ValidationRule запрещает __schema/__type
  (recon-поверхность).

Подключение: ``build_graphql_extensions()`` → ``strawberry.Schema(extensions=...)``
(единственная точка сборки схемы — auto_schema.build_auto_strawberry_schema).
"""

from __future__ import annotations

from typing import Any

from graphql import GraphQLError, ValidationRule
from strawberry.extensions import AddValidationRules, QueryDepthLimiter

MAX_QUERY_DEPTH = 12

_EXTENSION_CACHE: list[Any] | None = None


class NoIntrospectionRule(ValidationRule):
    """Запрещает интроспекцию (__schema/__type) вне development."""

    def enter_field(self, node: Any, *_args: Any) -> Any:
        """Отклоняет интроспекцию (``__schema``/``__type``) вне development.

        Args:
            node: AST-узел GraphQL-поля, посещаемый валидатором.
            *_args: Прочие позиционные аргументы visitor'а (unused).

        Returns:
            Результат :meth:`enter_field` базового visitor'а.

        """
        name = node.name.value
        if name in ("__schema", "__type"):
            self.report_error(
                GraphQLError(
                    "GraphQL introspection is disabled in this environment",
                    nodes=[node],
                )
            )
        return None


def _introspection_allowed() -> bool:
    try:
        from src.backend.core.config.settings import settings

        return settings.app.environment == "development"
    except Exception:  # noqa: BLE001 — fail-closed: конфиг недоступен → запрещаем
        return False


def build_graphql_extensions() -> list[Any]:
    """Собрать extensions для strawberry.Schema (кэш на процесс)."""
    global _EXTENSION_CACHE
    if _EXTENSION_CACHE is not None:
        return _EXTENSION_CACHE
    extensions: list[Any] = [QueryDepthLimiter(max_depth=MAX_QUERY_DEPTH)]
    if not _introspection_allowed():
        extensions.append(AddValidationRules([NoIntrospectionRule]))
    _EXTENSION_CACHE = extensions
    return extensions


def reset_extensions_cache() -> None:
    """Сброс кэша (для тестов и config hot-reload)."""
    global _EXTENSION_CACHE
    _EXTENSION_CACHE = None


__all__ = (
    "MAX_QUERY_DEPTH",
    "NoIntrospectionRule",
    "build_graphql_extensions",
    "reset_extensions_cache",
)
