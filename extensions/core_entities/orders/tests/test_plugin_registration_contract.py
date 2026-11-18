# ruff: noqa: S101
"""Регресс-тест: plugin-hook не затирает payload-модель, объявленную ядром.

Волна 34: каждый из core_entities-плагинов дублировал регистрацию
CRUD/actions, которую уже делает ядро
(``src.backend.dsl.commands.setup.registers_domains`` — ADR-0457).
Дублирование было не бесплатным: ``ActionRegistryAdapter`` (ядро)
оборачивает handler плагина в ``ActionHandlerSpec`` **без**
``payload_model`` и перезаписывает spec ядра
(``ActionHandlerRegistry.register_with_metadata`` при
``metadata.input_model is None`` пропускает conflict-check, а затем
``self._handlers[action] = handler``).

Итог: при включённом ``v11.plugin_loader_enabled`` валидация
request-body для ``orders.create_skb_order`` и ещё 5 actions молча
отключалась — маршрут отдавал 422 по OpenAPI-схеме, но в рантайме
принимал мусорный payload (fail-OPEN на границе доверия).

Инвариант: **у одного action'а один владелец регистрации**. Ядро владеет
CRUD и доменными actions; плагин — только тем, что ядро не регистрирует.
"""

from __future__ import annotations

import pytest

from extensions.core_entities.orders.plugin import OrdersPlugin

#: Actions, которые регистрирует ядро (registers_domains._register_orders).
_CORE_OWNED_ACTIONS = (
    "orders.add",
    "orders.get",
    "orders.update",
    "orders.delete",
    "orders.list",
    "orders.create_skb_order",
    "orders.get_result",
    "orders.get_file_and_json",
    "orders.get_file_from_storage",
    "orders.get_file_base64",
    "orders.get_file_link",
    "orders.send_order_data",
)


@pytest.mark.asyncio
async def test_orders_plugin_hook_does_not_drop_core_payload_model(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Plugin-hook не затирает payload-модель, объявленную ядром."""
    from src.backend.dsl.commands.action_registry import ActionHandlerRegistry
    from src.backend.dsl.commands.setup import helpers, registers_domains
    from src.backend.services.plugins.registries import ActionRegistryAdapter

    registry = ActionHandlerRegistry()
    monkeypatch.setattr(registers_domains, "action_handler_registry", registry)
    # CRUD-actions регистрирует helpers._register_crud_actions — у него
    # собственный импорт реестра, патчить оба.
    monkeypatch.setattr(helpers, "action_handler_registry", registry)

    # Каноническая регистрация ядра.
    registers_domains._register_orders()

    before = registry.get_metadata("orders.create_skb_order")
    assert before is not None
    assert before.input_model is not None, (
        "ядро обязано объявлять payload-модель для orders.create_skb_order"
    )

    # V11 PluginLoader: plugin-hook регистрирует action'ы через адаптер.
    await OrdersPlugin().on_register_actions(ActionRegistryAdapter(registry))

    after = registry.get_metadata("orders.create_skb_order")
    assert after is not None
    assert after.input_model is before.input_model, (
        "plugin-hook затирает payload-модель action'а — валидация request-body "
        "отключается молча (см. ADR-0457: регистрация — за ядром)"
    )


@pytest.mark.asyncio
async def test_orders_plugin_hook_registers_no_core_owned_actions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Plugin-hook не перерегистрирует actions, которыми владеет ядро.

    ``ActionHandlerRegistry.register_with_metadata`` подменяет объект
    метаданных на новый при каждой регистрации — поэтому identity-compare
    метаданных до/после однозначно показывает: hook action не трогал.
    """
    from src.backend.dsl.commands.action_registry import ActionHandlerRegistry
    from src.backend.dsl.commands.setup import helpers, registers_domains
    from src.backend.services.plugins.registries import ActionRegistryAdapter

    registry = ActionHandlerRegistry()
    monkeypatch.setattr(registers_domains, "action_handler_registry", registry)
    # CRUD-actions регистрирует helpers._register_crud_actions — у него
    # собственный импорт реестра, патчить оба.
    monkeypatch.setattr(helpers, "action_handler_registry", registry)
    registers_domains._register_orders()

    before = {action: registry.get_metadata(action) for action in _CORE_OWNED_ACTIONS}

    await OrdersPlugin().on_register_actions(ActionRegistryAdapter(registry))

    for action, meta in before.items():
        assert meta is not None, f"{action} должен быть зарегистрирован ядром"
        assert registry.get_metadata(action) is meta, (
            f"{action}: plugin-hook перерегистрировал action, которым владеет "
            f"ядро (ADR-0457: у action'а один владелец регистрации)"
        )
