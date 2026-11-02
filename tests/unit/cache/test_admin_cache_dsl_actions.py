"""Тесты DSL-действий admin cache invalidation (CACHE-1).

Проверяют что действия `admin.invalidate_cache_by_pattern`,
`admin.invalidate_cache_by_tag` и `admin.invalidate_table`
зарегистрированы в реестре и корректно диспетчеризируются.

Используют мок `CacheInvalidator`, чтобы не тянуть Redis-бэкенд
и DI-провайдеры.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.backend.dsl.commands.action_registry import action_handler_registry
from src.backend.schemas.invocation import (
    ActionCommandMetaSchema,
    ActionCommandSchema,
)


@pytest.fixture(autouse=True, scope="module")
def _register_admin_actions() -> None:
    """Регистрирует все actions через setup (вызывается register_action_handlers)."""
    from src.backend.dsl.commands.action_registry import action_handler_registry
    from src.backend.dsl.commands.setup import register_action_handlers

    # ADR-0404: реестр — ГЛОБАЛЬНОЕ состояние. Раньше в teardown вызывался
    # ``clear()``, и последующие suite'ы находили пустой реестр:
    # ``tests/unit/dsl/test_action_metadata_contract.py`` падал с
    # «Зарегистрировано подозрительно мало action: 0». Теперь состояние
    # восстанавливается, а не уничтожается.
    saved_handlers = dict(action_handler_registry._handlers)
    saved_metadata = dict(action_handler_registry._metadata)
    saved_middleware = list(action_handler_registry._middleware)

    register_action_handlers()
    yield
    action_handler_registry.clear()
    action_handler_registry._handlers.update(saved_handlers)
    action_handler_registry._metadata.update(saved_metadata)
    action_handler_registry._middleware.extend(saved_middleware)


@pytest.fixture
def mock_invalidator() -> MagicMock:
    """Мок CacheInvalidator с async invalidate_* методами."""
    inv = MagicMock()
    inv.invalidate_pattern = AsyncMock(return_value=5)
    inv.invalidate_tags = AsyncMock(return_value=3)
    inv.invalidate = AsyncMock(return_value=3)
    return inv


@pytest.fixture
def mock_invalidator_provider(mock_invalidator: MagicMock) -> MagicMock:
    """Мок get_cache_invalidator_provider, возвращающий мок-инвалидатор."""
    provider = MagicMock()
    provider.return_value = mock_invalidator
    return provider


@pytest.mark.anyio
class TestAdminCacheDslActions:
    """Тесты DSL-действий для admin cache invalidation."""

    async def test_invalidate_cache_by_pattern_registered(self) -> None:
        """admin.invalidate_cache_by_pattern зарегистрирован в реестре."""
        assert action_handler_registry.is_registered(
            "admin.invalidate_cache_by_pattern"
        )

    async def test_invalidate_cache_by_tag_registered(self) -> None:
        """admin.invalidate_cache_by_tag зарегистрирован в реестре."""
        assert action_handler_registry.is_registered("admin.invalidate_cache_by_tag")

    async def test_invalidate_table_registered(self) -> None:
        """admin.invalidate_table зарегистрирован в реестре."""
        assert action_handler_registry.is_registered("admin.invalidate_table")

    async def test_invalidate_cache_by_pattern_dispatches(
        self, mock_invalidator_provider: MagicMock, mock_invalidator: MagicMock
    ) -> None:
        """dispatch(admin.invalidate_cache_by_pattern) вызывает invalidate_pattern."""
        with patch(
            "src.backend.core.di.providers.get_cache_invalidator_provider",
            mock_invalidator_provider,
        ):
            command = ActionCommandSchema(
                action="admin.invalidate_cache_by_pattern",
                payload={"pattern": "entity:orders:*"},
                meta=ActionCommandMetaSchema(
                    principal="admin-test", permissions=["role:admin"]
                ),
            )
            result = await action_handler_registry.dispatch(command)

        assert result == {"pattern": "entity:orders:*", "removed": 5}
        mock_invalidator.invalidate_pattern.assert_called_once_with("entity:orders:*")

    async def test_invalidate_cache_by_tag_dispatches(
        self, mock_invalidator_provider: MagicMock, mock_invalidator: MagicMock
    ) -> None:
        """dispatch(admin.invalidate_cache_by_tag) вызывает invalidate_tags."""
        with patch(
            "src.backend.core.di.providers.get_cache_invalidator_provider",
            mock_invalidator_provider,
        ):
            command = ActionCommandSchema(
                action="admin.invalidate_cache_by_tag",
                payload={"tags": ["entity:orders", "table:orders"]},
                meta=ActionCommandMetaSchema(
                    principal="admin-test", permissions=["role:admin"]
                ),
            )
            result = await action_handler_registry.dispatch(command)

        assert result["tags"] == ["entity:orders", "table:orders"]
        assert result["removed"] == 3
        mock_invalidator.invalidate_tags.assert_called_once_with(
            "entity:orders", "table:orders"
        )

    async def test_admin_action_denied_without_role(
        self, mock_invalidator_provider: MagicMock, mock_invalidator: MagicMock
    ) -> None:
        """admin.* без role:admin → отказ (ADR-0421, fail-closed)."""
        from src.backend.dsl.commands.action_registry import (
            ActionPermissionDeniedError,
        )

        with patch(
            "src.backend.core.di.providers.get_cache_invalidator_provider",
            mock_invalidator_provider,
        ):
            command = ActionCommandSchema(
                action="admin.invalidate_table",
                payload={"table": "orders"},
                meta=ActionCommandMetaSchema(principal="anonymous"),
            )
            with pytest.raises(ActionPermissionDeniedError) as exc:
                await action_handler_registry.dispatch(command)

        assert exc.value.status_code == 403
        mock_invalidator.invalidate_table.assert_not_called()

    async def test_invalidate_table_dispatches(
        self, mock_invalidator_provider: MagicMock, mock_invalidator: MagicMock
    ) -> None:
        """dispatch(admin.invalidate_table) формирует тег table:<name>."""
        with patch(
            "src.backend.core.di.providers.get_cache_invalidator_provider",
            mock_invalidator_provider,
        ):
            command = ActionCommandSchema(
                action="admin.invalidate_table",
                payload={"table": "orders"},
                meta=ActionCommandMetaSchema(
                    principal="admin-test", permissions=["role:admin"]
                ),
            )
            result = await action_handler_registry.dispatch(command)

        assert result["table"] == "orders"
        assert result["tag"] == "table:orders"
        assert result["removed"] == 3
        mock_invalidator.invalidate_tags.assert_called_once_with("table:orders")

    async def test_invalidate_cache_by_pattern_returns_zero_on_no_match(
        self, mock_invalidator_provider: MagicMock, mock_invalidator: MagicMock
    ) -> None:
        """Паттерн без совпадений возвращает removed=0."""
        mock_invalidator.invalidate_pattern = AsyncMock(return_value=0)
        with patch(
            "src.backend.core.di.providers.get_cache_invalidator_provider",
            mock_invalidator_provider,
        ):
            command = ActionCommandSchema(
                action="admin.invalidate_cache_by_pattern",
                payload={"pattern": "nonexistent:*"},
                meta=ActionCommandMetaSchema(
                    principal="admin-test", permissions=["role:admin"]
                ),
            )
            result = await action_handler_registry.dispatch(command)

        assert result == {"pattern": "nonexistent:*", "removed": 0}
