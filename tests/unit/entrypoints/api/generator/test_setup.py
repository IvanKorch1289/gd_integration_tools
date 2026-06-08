"""Unit-тесты для ``src.backend.entrypoints.api.generator.setup``.

Модуль импортирует сервис-геттеры из ``extensions/*``; в тестах они
подменяются фейковыми пакетами через ``sys.modules``, чтобы не тянуть
бизнес-логику extensions и тяжёлые зависимости.
"""

# ruff: noqa: S101

from __future__ import annotations

import importlib
import sys
import types
from typing import Any
from unittest.mock import MagicMock

import pytest

from src.backend.dsl.commands.action_registry import ActionHandlerRegistry


def _mock_extension_modules(monkeypatch: pytest.MonkeyPatch) -> dict[str, Any]:
    """Создаёт фейковое дерево модулей для ``extensions/*`` и workflows."""
    names = [
        "extensions",
        "extensions.core_entities",
        "extensions.core_entities.orderkinds",
        "extensions.core_entities.orderkinds.services",
        "extensions.core_entities.orderkinds.services.orderkinds",
        "extensions.core_entities.orders",
        "extensions.core_entities.orders.services",
        "extensions.core_entities.orders.services.orders",
        "src.backend.workflows",
        "src.backend.workfolws.workflows_service",
    ]
    mods: dict[str, Any] = {}
    for name in names:
        mod = types.ModuleType(name)
        mod.__path__ = []
        mods[name] = mod
        monkeypatch.setitem(sys.modules, name, mod)

    # Связываем родителей с подмодулями.
    mods["extensions"].core_entities = mods["extensions.core_entities"]
    mods["extensions.core_entities"].orderkinds = mods[
        "extensions.core_entities.orderkinds"
    ]
    mods["extensions.core_entities.orderkinds"].services = mods[
        "extensions.core_entities.orderkinds.services"
    ]
    mods["extensions.core_entities"].orders = mods["extensions.core_entities.orders"]
    mods["extensions.core_entities.orders"].services = mods[
        "extensions.core_entities.orders.services"
    ]

    # Сервис-геттеры — достаточно быть вызываемыми MagicMock.
    mods[
        "extensions.core_entities.orderkinds.services.orderkinds"
    ].get_order_kind_service = MagicMock()
    mods[
        "extensions.core_entities.orders.services.orders"
    ].get_order_service = MagicMock()
    mods["src.backend.workfolws.workflows_service"].get_workflows_service = MagicMock()

    return mods


@pytest.fixture
def setup_module(monkeypatch: pytest.MonkeyPatch) -> Any:
    """Возвращает свежий инстанс модуля ``setup`` с замоканными extensions."""
    _mock_extension_modules(monkeypatch)
    from src.backend.entrypoints.api.generator import setup as mod

    importlib.reload(mod)
    return mod


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
