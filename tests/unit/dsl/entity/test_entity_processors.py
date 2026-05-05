"""Unit-тесты для DSL entity-процессоров (Wave 11 CRUD).

Покрытие:
    * Инстанцирование 5 процессоров (Create/Get/Update/Delete/List)
    * Корректное формирование ``<entity>.<verb>`` action в process()
    * Round-trip ``to_spec()``
    * Валидация некорректных входных данных (entity с точкой, payload != dict)
"""

# ruff: noqa: S101

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.backend.dsl.engine.exchange import Exchange, ExchangeStatus, Message
from src.backend.dsl.engine.processors.entity import (
    EntityCreateProcessor,
    EntityDeleteProcessor,
    EntityGetProcessor,
    EntityListProcessor,
    EntityUpdateProcessor,
)
from src.backend.schemas.invocation import ActionCommandSchema

# ── Helpers ──────────────────────────────────────────────────────────────


def _make_exchange(body: Any = None, headers: dict[str, Any] | None = None) -> Exchange[Any]:
    """Создаёт реальный Exchange c заданным in_message."""
    return Exchange(in_message=Message(body=body, headers=headers or {}))


def _make_context(dispatch_result: Any = None) -> MagicMock:
    """Создаёт mock ExecutionContext c AsyncMock для action_registry.dispatch."""
    context = MagicMock()
    context.action_registry = MagicMock()
    context.action_registry.dispatch = AsyncMock(return_value=dispatch_result)
    return context


def _dispatched_command(context: MagicMock) -> ActionCommandSchema:
    """Извлекает ActionCommandSchema из вызова dispatch()."""
    args, kwargs = context.action_registry.dispatch.call_args
    command = args[0] if args else kwargs["command"]
    assert isinstance(command, ActionCommandSchema)
    return command


# ── EntityCreateProcessor ────────────────────────────────────────────────


class TestEntityCreateProcessor:
    """Тесты для EntityCreateProcessor."""

    def test_instantiate_defaults(self) -> None:
        """Создаётся с дефолтными параметрами."""
        processor = EntityCreateProcessor(entity="user")
        assert processor.name == "entity_create:user"

    def test_instantiate_custom(self) -> None:
        """Принимает custom payload_from / result_property / name."""
        processor = EntityCreateProcessor(
            entity="orders",
            payload_from="body.data",
            result_property="created",
            name="custom_create",
        )
        assert processor.name == "custom_create"

    def test_entity_with_dot_raises(self) -> None:
        """Имя сущности не может содержать точку."""
        with pytest.raises(ValueError, match="entity"):
            EntityCreateProcessor(entity="bad.name")

    def test_empty_entity_raises(self) -> None:
        """Пустое имя сущности недопустимо."""
        with pytest.raises(ValueError, match="entity"):
            EntityCreateProcessor(entity="")

    async def test_dispatches_create_action(self) -> None:
        """process() формирует action ``user.create`` и пишет результат в exchange."""
        processor = EntityCreateProcessor(entity="user")
        exchange = _make_exchange(body={"name": "alice"})
        context = _make_context(dispatch_result={"id": "u1", "name": "alice"})

        await processor.process(exchange, context)

        context.action_registry.dispatch.assert_awaited_once()
        command = _dispatched_command(context)
        assert command.action == "user.create"
        assert command.payload == {"name": "alice"}
        assert exchange.get_property("action_result") == {"id": "u1", "name": "alice"}
        assert exchange.out_message is not None
        assert exchange.out_message.body == {"id": "u1", "name": "alice"}

    async def test_non_dict_payload_fails(self) -> None:
        """Если payload_from вернул не dict — exchange завершается ошибкой."""
        processor = EntityCreateProcessor(entity="user")
        exchange = _make_exchange(body="raw-string")
        context = _make_context()

        await processor.process(exchange, context)

        context.action_registry.dispatch.assert_not_awaited()
        assert exchange.status == ExchangeStatus.failed
        assert exchange.error is not None
        assert "payload_from" in exchange.error

    def test_to_spec_roundtrip(self) -> None:
        """to_spec() возвращает kind ``entity_create`` с полями процессора."""
        processor = EntityCreateProcessor(
            entity="user", payload_from="body.data", result_property="created"
        )
        spec = processor.to_spec()

        assert "entity_create" in spec
        assert spec["entity_create"] == {
            "entity": "user",
            "payload_from": "body.data",
            "result_property": "created",
        }


# ── EntityGetProcessor ───────────────────────────────────────────────────


class TestEntityGetProcessor:
    """Тесты для EntityGetProcessor."""

    def test_instantiate_defaults(self) -> None:
        """Создаётся с дефолтными параметрами."""
        processor = EntityGetProcessor(entity="user")
        assert processor.name == "entity_get:user"

    async def test_dispatches_get_action(self) -> None:
        """process() формирует action ``user.get`` с id из body."""
        processor = EntityGetProcessor(entity="user")
        exchange = _make_exchange(body={"id": "u-42"})
        context = _make_context(dispatch_result={"id": "u-42", "name": "bob"})

        await processor.process(exchange, context)

        context.action_registry.dispatch.assert_awaited_once()
        command = _dispatched_command(context)
        assert command.action == "user.get"
        assert command.payload == {"id": "u-42"}
        assert exchange.get_property("action_result") == {"id": "u-42", "name": "bob"}

    async def test_missing_id_fails(self) -> None:
        """Отсутствие id в body приводит к exchange.fail()."""
        processor = EntityGetProcessor(entity="user")
        exchange = _make_exchange(body={})
        context = _make_context()

        await processor.process(exchange, context)

        context.action_registry.dispatch.assert_not_awaited()
        assert exchange.status == ExchangeStatus.failed
        assert exchange.error is not None
        assert "id_from" in exchange.error

    def test_to_spec_roundtrip(self) -> None:
        """to_spec() возвращает kind ``entity_get`` с полями процессора."""
        processor = EntityGetProcessor(
            entity="orders", id_from="properties.order_id", result_property="ord"
        )
        spec = processor.to_spec()

        assert "entity_get" in spec
        assert spec["entity_get"] == {
            "entity": "orders",
            "id_from": "properties.order_id",
            "result_property": "ord",
        }


# ── EntityUpdateProcessor ────────────────────────────────────────────────


class TestEntityUpdateProcessor:
    """Тесты для EntityUpdateProcessor."""

    def test_instantiate_defaults(self) -> None:
        """Создаётся с дефолтными параметрами."""
        processor = EntityUpdateProcessor(entity="user")
        assert processor.name == "entity_update:user"

    async def test_dispatches_update_action(self) -> None:
        """process() формирует action ``user.update`` c id+data в payload."""
        processor = EntityUpdateProcessor(entity="user")
        exchange = _make_exchange(body={"id": "u-7", "name": "carol"})
        context = _make_context(dispatch_result={"id": "u-7", "name": "carol"})

        await processor.process(exchange, context)

        context.action_registry.dispatch.assert_awaited_once()
        command = _dispatched_command(context)
        assert command.action == "user.update"
        assert command.payload == {
            "id": "u-7",
            "data": {"id": "u-7", "name": "carol"},
        }

    async def test_missing_id_fails(self) -> None:
        """Отсутствие id приводит к exchange.fail()."""
        processor = EntityUpdateProcessor(entity="user")
        exchange = _make_exchange(body={"name": "carol"})
        context = _make_context()

        await processor.process(exchange, context)

        context.action_registry.dispatch.assert_not_awaited()
        assert exchange.status == ExchangeStatus.failed
        assert "id_from" in (exchange.error or "")

    async def test_non_dict_payload_fails(self) -> None:
        """payload != dict приводит к exchange.fail()."""
        processor = EntityUpdateProcessor(
            entity="user", id_from="header.X-Id", payload_from="body"
        )
        exchange = _make_exchange(body="not-a-dict", headers={"X-Id": "u-9"})
        context = _make_context()

        await processor.process(exchange, context)

        context.action_registry.dispatch.assert_not_awaited()
        assert exchange.status == ExchangeStatus.failed
        assert "payload_from" in (exchange.error or "")

    def test_to_spec_roundtrip(self) -> None:
        """to_spec() возвращает kind ``entity_update`` с полями процессора."""
        processor = EntityUpdateProcessor(
            entity="orders",
            id_from="body.order_id",
            payload_from="body.data",
            result_property="updated",
        )
        spec = processor.to_spec()

        assert "entity_update" in spec
        assert spec["entity_update"] == {
            "entity": "orders",
            "id_from": "body.order_id",
            "payload_from": "body.data",
            "result_property": "updated",
        }


# ── EntityDeleteProcessor ────────────────────────────────────────────────


class TestEntityDeleteProcessor:
    """Тесты для EntityDeleteProcessor."""

    def test_instantiate_defaults(self) -> None:
        """Создаётся с дефолтными параметрами."""
        processor = EntityDeleteProcessor(entity="user")
        assert processor.name == "entity_delete:user"

    async def test_dispatches_delete_action(self) -> None:
        """process() формирует action ``user.delete`` c id в payload."""
        processor = EntityDeleteProcessor(entity="user")
        exchange = _make_exchange(body={"id": "u-1"})
        context = _make_context(dispatch_result=True)

        await processor.process(exchange, context)

        context.action_registry.dispatch.assert_awaited_once()
        command = _dispatched_command(context)
        assert command.action == "user.delete"
        assert command.payload == {"id": "u-1"}
        assert exchange.get_property("action_result") is True

    async def test_missing_id_fails(self) -> None:
        """Отсутствие id приводит к exchange.fail()."""
        processor = EntityDeleteProcessor(entity="user")
        exchange = _make_exchange(body={})
        context = _make_context()

        await processor.process(exchange, context)

        context.action_registry.dispatch.assert_not_awaited()
        assert exchange.status == ExchangeStatus.failed

    def test_to_spec_roundtrip(self) -> None:
        """to_spec() возвращает kind ``entity_delete`` с полями процессора."""
        processor = EntityDeleteProcessor(
            entity="orders", id_from="body.order_id", result_property="deleted"
        )
        spec = processor.to_spec()

        assert "entity_delete" in spec
        assert spec["entity_delete"] == {
            "entity": "orders",
            "id_from": "body.order_id",
            "result_property": "deleted",
        }


# ── EntityListProcessor ──────────────────────────────────────────────────


class TestEntityListProcessor:
    """Тесты для EntityListProcessor."""

    def test_instantiate_defaults(self) -> None:
        """Создаётся с дефолтными параметрами."""
        processor = EntityListProcessor(entity="user")
        assert processor.name == "entity_list:user"

    async def test_dispatches_list_action_minimal(self) -> None:
        """process() формирует action ``user.list`` без page/size, если не заданы."""
        processor = EntityListProcessor(entity="user")
        exchange = _make_exchange(body={"filters": {"role": "admin"}})
        context = _make_context(dispatch_result={"items": [], "total": 0})

        await processor.process(exchange, context)

        context.action_registry.dispatch.assert_awaited_once()
        command = _dispatched_command(context)
        assert command.action == "user.list"
        assert command.payload == {"filters": {"role": "admin"}}

    async def test_dispatches_list_action_with_pagination(self) -> None:
        """process() кладёт page/size в payload, если заданы статически."""
        processor = EntityListProcessor(entity="orders", page=2, size=25)
        exchange = _make_exchange(body={"filters": {"status": "active"}})
        context = _make_context(dispatch_result={"items": [], "total": 0})

        await processor.process(exchange, context)

        command = _dispatched_command(context)
        assert command.action == "orders.list"
        assert command.payload == {
            "filters": {"status": "active"},
            "page": 2,
            "size": 25,
        }

    async def test_dispatches_list_action_pagination_from_exchange(self) -> None:
        """page_from / size_from извлекаются из exchange."""
        processor = EntityListProcessor(
            entity="orders",
            filters_from=None,
            page_from="body.page",
            size_from="body.size",
        )
        exchange = _make_exchange(body={"page": 3, "size": 10})
        context = _make_context(dispatch_result={"items": [], "total": 0})

        await processor.process(exchange, context)

        command = _dispatched_command(context)
        assert command.payload == {"filters": {}, "page": 3, "size": 10}

    async def test_filters_non_dict_becomes_empty(self) -> None:
        """Если filters_from вернул не-dict — в payload пустой dict."""
        processor = EntityListProcessor(entity="user", filters_from="body.filters")
        exchange = _make_exchange(body={"filters": "not-a-dict"})
        context = _make_context(dispatch_result={"items": []})

        await processor.process(exchange, context)

        command = _dispatched_command(context)
        assert command.payload == {"filters": {}}

    def test_to_spec_roundtrip_minimal(self) -> None:
        """to_spec() возвращает только заданные поля."""
        processor = EntityListProcessor(entity="user")
        spec = processor.to_spec()

        assert "entity_list" in spec
        assert spec["entity_list"] == {
            "entity": "user",
            "result_property": "action_result",
            "filters_from": "body.filters",
        }

    def test_to_spec_roundtrip_full(self) -> None:
        """to_spec() сохраняет все опциональные поля."""
        processor = EntityListProcessor(
            entity="orders",
            filters_from="body.filters",
            page=1,
            size=50,
            page_from="body.page",
            size_from="body.size",
            result_property="page_result",
        )
        spec = processor.to_spec()

        assert spec["entity_list"] == {
            "entity": "orders",
            "result_property": "page_result",
            "filters_from": "body.filters",
            "page": 1,
            "size": 50,
            "page_from": "body.page",
            "size_from": "body.size",
        }
