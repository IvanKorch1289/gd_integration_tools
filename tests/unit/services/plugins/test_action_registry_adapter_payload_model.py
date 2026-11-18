"""F-01e — ``ActionRegistryAdapter`` не затирает ``payload_model`` ядра.

Аудит F-01e (волна 35): ``ActionRegistryAdapter.register`` всегда создавал
``ActionHandlerSpec(payload_model=None)`` и перезаписывал запись, уже
зарегистрированную ядром (``ActionHandlerRegistry.register_with_metadata``
при ``metadata.input_model is None`` пропускает conflict-check, а затем
делает ``self._handlers[action] = handler``).

Итог: валидация request-body для actions, объявленных ядром
(``orders.create_skb_order`` и др.), молча отключалась — маршрут отдавал
422 по OpenAPI-схеме, но в рантайме принимал мусорный payload (fail-OPEN
на границе доверия).

Инварианты:
* регистрация через адаптер **сохраняет** ``payload_model`` ядра;
* валидация payload продолжает работать после регистрации через адаптер;
* требуемые права (``ActionMetadata.permissions`` — аналог
  ``required_capability`` для action'а) не теряются;
* новый action (не зарегистрированный ядром) регистрируется как раньше;
* конфликтующая payload-модель → fail-closed (``ValueError``).
"""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import BaseModel, ValidationError

from src.backend.dsl.commands.action_registry import (
    ActionHandlerRegistry,
    ActionHandlerSpec,
)
from src.backend.schemas.invocation import ActionCommandSchema
from src.backend.services.plugins.registries import ActionRegistryAdapter

pytestmark = pytest.mark.unit


class _OrderIdQuery(BaseModel):
    """Payload-модель action'а, объявленная ядром."""

    order_id: int


class _OtherQuery(BaseModel):
    """Другая payload-модель — для проверки fail-closed на конфликте."""

    order_id: str


async def _core_handler(**kwargs: Any) -> dict[str, Any]:
    """Обработчик ядра: возвращает переданные kwargs."""
    return kwargs


async def _plugin_handler(**kwargs: Any) -> dict[str, Any]:
    """Обработчик плагина."""
    return {"from": "plugin", **kwargs}


def _register_core_action(registry: ActionHandlerRegistry) -> None:
    """Регистрирует action ядром — с payload-моделью (как ``registers_domains``)."""
    registry.register(
        action="orders.create_skb_order",
        service_getter=_core_handler,
        service_method="__call__",
        payload_model=_OrderIdQuery,
    )


class TestAdapterPreservesCorePayloadModel:
    """Адаптер не обнуляет объявленную ядром payload-модель."""

    def test_payload_model_preserved(self) -> None:
        """``payload_model`` существующей записи не затирается на ``None``."""
        registry = ActionHandlerRegistry()
        _register_core_action(registry)

        ActionRegistryAdapter(registry).register(
            "orders.create_skb_order", _plugin_handler
        )

        handler = registry.get_handler("orders.create_skb_order")
        assert handler is not None
        assert handler.payload_model is _OrderIdQuery, (
            "адаптер обнулил payload_model ядра — валидация request-body "
            "отключается молча (аудит F-01e)"
        )

    def test_metadata_input_model_preserved(self) -> None:
        """``ActionMetadata.input_model`` ядра не теряется."""
        registry = ActionHandlerRegistry()
        _register_core_action(registry)

        ActionRegistryAdapter(registry).register(
            "orders.create_skb_order", _plugin_handler
        )

        metadata = registry.get_metadata("orders.create_skb_order")
        assert metadata is not None
        assert metadata.input_model is _OrderIdQuery

    async def test_dispatch_still_validates_payload(self) -> None:
        """Валидация payload не отключается после регистрации через адаптер."""
        registry = ActionHandlerRegistry()
        _register_core_action(registry)

        ActionRegistryAdapter(registry).register(
            "orders.create_skb_order", _plugin_handler
        )

        # Негативный сценарий: payload не соответствует модели → 422-подобная
        # ошибка валидации, а не «мусор прошёл в обработчик».
        with pytest.raises(ValidationError):
            await registry.dispatch(
                ActionCommandSchema(
                    action="orders.create_skb_order", payload={"order_id": "не-int"}
                )
            )

    async def test_dispatch_accepts_valid_payload(self) -> None:
        """Валидный payload доходит до обработчика плагина."""
        registry = ActionHandlerRegistry()
        _register_core_action(registry)

        ActionRegistryAdapter(registry).register(
            "orders.create_skb_order", _plugin_handler
        )

        result = await registry.dispatch(
            ActionCommandSchema(
                action="orders.create_skb_order", payload={"order_id": 42}
            )
        )
        assert result == {"from": "plugin", "order_id": 42}

    def test_permissions_preserved(self) -> None:
        """Требуемые права action'а не теряются при регистрации через адаптер."""
        from src.backend.core.interfaces.action_dispatcher import ActionMetadata

        registry = ActionHandlerRegistry()
        registry.register_with_metadata(
            action="orders.create_skb_order",
            handler=ActionHandlerSpec(
                action="orders.create_skb_order",
                service_getter=_core_handler,
                service_method="__call__",
                payload_model=_OrderIdQuery,
            ),
            metadata=ActionMetadata(
                action="orders.create_skb_order",
                input_model=_OrderIdQuery,
                permissions=("role:admin",),
            ),
        )

        ActionRegistryAdapter(registry).register(
            "orders.create_skb_order", _plugin_handler
        )

        metadata = registry.get_metadata("orders.create_skb_order")
        assert metadata is not None
        assert metadata.permissions == ("role:admin",), (
            "адаптер обнулил требуемые права action'а — проверка доступа "
            "ослабла (аналог required_capability)"
        )


class TestAdapterNewAction:
    """Новый action (не объявленный ядром) регистрируется как раньше."""

    def test_new_action_registered(self) -> None:
        """Action плагина попадает в реестр и вызывается."""
        registry = ActionHandlerRegistry()

        ActionRegistryAdapter(registry).register("demo.echo", _plugin_handler)

        assert registry.is_registered("demo.echo")
        handler = registry.get_handler("demo.echo")
        assert handler is not None
        assert handler.payload_model is None

    async def test_new_action_dispatches(self) -> None:
        """Новый action плагина вызывается через dispatch."""
        registry = ActionHandlerRegistry()

        ActionRegistryAdapter(registry).register("demo.echo", _plugin_handler)

        result = await registry.dispatch(
            ActionCommandSchema(action="demo.echo", payload={"x": 1})
        )
        assert result == {"from": "plugin", "x": 1}

    def test_conflicting_payload_model_fails_closed(self) -> None:
        """Конфликтующая payload-модель → отказ (fail-closed), не тихий overwrite."""
        from src.backend.core.interfaces.action_dispatcher import ActionMetadata

        registry = ActionHandlerRegistry()
        _register_core_action(registry)

        adapter = ActionRegistryAdapter(registry)
        with pytest.raises(ValueError, match="conflict"):
            adapter.register(
                "orders.create_skb_order",
                _plugin_handler,
                spec=ActionMetadata(
                    action="orders.create_skb_order", input_model=_OtherQuery
                ),
            )

        # Запись ядра не повреждена.
        handler = registry.get_handler("orders.create_skb_order")
        assert handler is not None
        assert handler.payload_model is _OrderIdQuery


def test_adapter_target_registry_api() -> None:
    """Аксессор ``get_handler`` — часть публичного API реестра действий."""
    registry = ActionHandlerRegistry()
    assert registry.get_handler("missing") is None

    spec = ActionHandlerSpec(
        action="a.b", service_getter=lambda: None, service_method="call"
    )
    registry.register(
        action="a.b",
        service_getter=spec.service_getter,
        service_method=spec.service_method,
    )
    assert registry.get_handler("a.b") is not None
