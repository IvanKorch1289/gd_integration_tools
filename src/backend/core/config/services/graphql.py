"""GraphQL service settings (S163 W13).

Ранее GraphQL использовал Strawberry defaults (no query timeout — запрос
может висеть бесконечно). Per R-V15-12 все I/O операции должны иметь
timeout.

DSL override (per-route): ``route.toml::[transport.graphql] query_timeout_s``,
``max_query_depth`` — реализуется в S163 W14.

Pattern: ``MailSettings`` / ``CacheSettings`` — BaseSettingsWithLoader +
yaml_group + env_prefix.
"""

from __future__ import annotations

from typing import ClassVar

from pydantic import Field
from pydantic_settings import SettingsConfigDict

from src.backend.core.config.config_loader import BaseSettingsWithLoader

__all__ = ("GraphQLSettings", "graphql_settings")


class GraphQLSettings(BaseSettingsWithLoader):
    """Стандартные настройки GraphQL-сервиса.

    Используются в ``entrypoints/graphql/auto_schema.py`` для:
        * query timeout (Strawberry execute_async с asyncio.wait_for)
        * max query depth (защита от deeply-nested queries)
        * max query complexity (защита от expensive queries)

    Per-route override через ``route.toml::[transport.graphql]`` (S163 W14).
    """

    yaml_group: ClassVar[str] = "graphql"
    model_config = SettingsConfigDict(env_prefix="GRAPHQL_", extra="forbid")

    query_timeout_s: float = Field(
        default=30.0,
        gt=0,
        description="Таймаут на выполнение GraphQL-запроса (секунды).",
    )

    max_query_depth: int = Field(
        default=15,
        gt=0,
        description="Макс. глубина GraphQL-запроса (защита от deeply-nested).",
    )

    max_query_complexity: int = Field(
        default=1000, gt=0, description="Макс. complexity score для GraphQL-запроса."
    )

    enable_introspection: bool = Field(
        default=True, description="Разрешить introspection queries (отключить в prod)."
    )


graphql_settings = GraphQLSettings()
"""Глобальный экземпляр GraphQLSettings."""
