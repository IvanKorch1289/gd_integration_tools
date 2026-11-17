"""Unit-тесты для ``src.backend.entrypoints.api.generator.setup``.

Модуль получает сервис-геттеры и схемы расширений через core-реестр
(ADR-0457); в тестах они подменяются фейковыми ресурсами через
``register_extension_resource``, чтобы не тянуть бизнес-логику extensions
и тяжёлые зависимости.
"""

from __future__ import annotations

import importlib
from typing import Any
from unittest.mock import MagicMock

import pytest

from src.backend.core.extension_registry import (
    register_extension_resource,
    reset_extension_resources,
)
from src.backend.dsl.commands.action_registry import ActionHandlerRegistry


@pytest.fixture
def setup_module() -> Any:
    """Возвращает свежий инстанс модуля ``setup`` с фейковыми ресурсами."""
    reset_extension_resources()
    register_extension_resource("orders", "schema", "id_path", MagicMock())
    register_extension_resource("orders", "service", "orders", MagicMock())
    register_extension_resource("orderkinds", "service", "orderkinds", MagicMock())

    from src.backend.entrypoints.api.generator import setup as mod

    importlib.reload(mod)
    yield mod

    reset_extension_resources()


@pytest.fixture
def isolated_registry(
    setup_module: Any, monkeypatch: pytest.MonkeyPatch
) -> ActionHandlerRegistry:
    """Чистый реестр и сброшенный флаг _is_registered для каждого теста."""
    registry = ActionHandlerRegistry()
    monkeypatch.setattr(setup_module, "action_handler_registry", registry)
    monkeypatch.setattr(setup_module, "_is_registered", False)
    return registry


@pytest.mark.unit
class TestRegisterActionHandlers:
    def test_register_action_handlers_first_call_registers_all_actions(
        self, setup_module: Any, isolated_registry: ActionHandlerRegistry
    ) -> None:
        setup_module.register_action_handlers()

        actions = isolated_registry.list_actions()
        assert len(actions) == 6
        expected = (
            "orders.create_skb_order",
            "orders.fetch_result",
            "orders.send_result",
            "orderkinds.sync_from_skb",
            "workflows.send_email_notification",
            "workflows.order_processing",
        )
        for action in expected:
            assert action in actions

    def test_register_action_handlers_second_call_is_noop(
        self,
        setup_module: Any,
        isolated_registry: ActionHandlerRegistry,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        spy = MagicMock(wraps=isolated_registry.register_many)
        monkeypatch.setattr(isolated_registry, "register_many", spy)

        setup_module.register_action_handlers()
        setup_module.register_action_handlers()

        spy.assert_called_once()
        assert len(isolated_registry.list_actions()) == 6

    def test_register_action_handlers_sets_flag(
        self, setup_module: Any, isolated_registry: ActionHandlerRegistry
    ) -> None:
        assert setup_module._is_registered is False
        setup_module.register_action_handlers()
        assert setup_module._is_registered is True

    def test_resources_are_resolved_via_extension_registry(
        self, setup_module: Any
    ) -> None:
        """Модуль берёт объекты расширений из core-реестра (ADR-0457)."""
        from src.backend.core.extension_registry import get_extension_resource

        assert setup_module.OrderIdPathSchema is get_extension_resource(
            "orders", "schema", "id_path"
        )
        assert setup_module.get_order_service is get_extension_resource(
            "orders", "service", "orders"
        )
        assert setup_module.get_order_kind_service is get_extension_resource(
            "orderkinds", "service", "orderkinds"
        )
