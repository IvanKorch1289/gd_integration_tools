# ruff: noqa: S101
"""Unit-тесты ``AuditProcessor`` (Wave 11).

Покрывают:
    * Валидацию ``outcome`` (success/failure/denied/error).
    * Обязательность ``action`` или ``action_from``.
    * Запись события через мок ``ImmutableAuditStore.append``.
    * Round-trip ``to_spec()``.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.dsl.engine.exchange import Exchange, ExchangeStatus, Message
from src.dsl.engine.processors.audit import AuditProcessor


def _make_exchange(
    body: Any | None = None, properties: dict[str, Any] | None = None
) -> Exchange[Any]:
    """Создаёт ``Exchange`` с заданным body и properties."""
    exchange: Exchange[Any] = Exchange(in_message=Message(body=body))
    if properties:
        exchange.properties.update(properties)
    return exchange


# ----------------------------- Валидация конструктора --------------------------


def test_audit_requires_action_or_action_from() -> None:
    """Без ``action`` и без ``action_from`` — конструктор падает."""
    with pytest.raises(ValueError, match="action или action_from"):
        AuditProcessor(outcome="success")


@pytest.mark.parametrize("outcome", ["success", "failure", "denied", "error"])
def test_audit_accepts_valid_outcomes(outcome: str) -> None:
    """Все валидные outcome-значения принимаются конструктором."""
    proc = AuditProcessor(action="user.login", outcome=outcome)
    assert proc is not None


@pytest.mark.parametrize(
    "outcome", ["pending", "ok", "fail", "rejected", "", "Success"]
)
def test_audit_rejects_invalid_outcome(outcome: str) -> None:
    """Невалидный outcome -> ValueError."""
    with pytest.raises(ValueError, match="outcome="):
        AuditProcessor(action="x", outcome=outcome)


def test_audit_default_name_uses_action() -> None:
    """Имя процессора собирается из action."""
    proc = AuditProcessor(action="order.created")
    assert proc.name == "audit:order.created"


def test_audit_name_for_dynamic_action_from() -> None:
    """Имя процессора при dynamic action_from."""
    proc = AuditProcessor(action_from="properties.action")
    assert proc.name == "audit:properties.action"


# ------------------------------ process() / store ------------------------------


async def test_audit_appends_to_store_static_action() -> None:
    """Статические поля передаются в ``store.append`` без модификации."""
    fake_store = MagicMock()
    fake_store.append = AsyncMock(return_value="hash-abc")

    proc = AuditProcessor(action="user.login", actor="alice", outcome="success")
    exchange = _make_exchange()
    context = MagicMock()

    with patch.object(AuditProcessor, "_build_store", return_value=fake_store):
        await proc.process(exchange, context)

    fake_store.append.assert_awaited_once()
    kwargs = fake_store.append.await_args.kwargs
    assert kwargs["action"] == "user.login"
    assert kwargs["actor"] == "alice"
    assert kwargs["outcome"] == "success"
    assert kwargs["resource"] is None
    assert kwargs["metadata"] is None
    assert exchange.properties["audit_event_hash"] == "hash-abc"
    assert exchange.status != ExchangeStatus.failed


async def test_audit_resolves_action_from_expression() -> None:
    """``action_from`` извлекается из ``exchange.properties``."""
    fake_store = MagicMock()
    fake_store.append = AsyncMock(return_value="h1")

    proc = AuditProcessor(action_from="properties.evt", outcome="success")
    exchange = _make_exchange(properties={"evt": "order.created"})

    with patch.object(AuditProcessor, "_build_store", return_value=fake_store):
        await proc.process(exchange, MagicMock())

    fake_store.append.assert_awaited_once()
    assert fake_store.append.await_args.kwargs["action"] == "order.created"


async def test_audit_resolves_actor_resource_metadata_from_expressions() -> None:
    """Все *_from-поля извлекаются из exchange."""
    fake_store = MagicMock()
    fake_store.append = AsyncMock(return_value="h2")

    proc = AuditProcessor(
        action="order.created",
        actor_from="properties.user_id",
        resource_from="properties.order_id",
        metadata_from="properties.meta",
        tenant_id_from="properties.tenant",
        correlation_id_from="properties.corr",
        outcome="success",
    )
    exchange = _make_exchange(
        properties={
            "user_id": "u-42",
            "order_id": "o-7",
            "meta": {"amount": 100},
            "tenant": "t-1",
            "corr": "c-1",
        }
    )

    with patch.object(AuditProcessor, "_build_store", return_value=fake_store):
        await proc.process(exchange, MagicMock())

    kwargs = fake_store.append.await_args.kwargs
    assert kwargs["actor"] == "u-42"
    assert kwargs["resource"] == "o-7"
    assert kwargs["metadata"] == {"amount": 100}
    assert kwargs["tenant_id"] == "t-1"
    assert kwargs["correlation_id"] == "c-1"


async def test_audit_wraps_non_dict_metadata() -> None:
    """Если metadata_from вернул не dict — обернуть в ``{'value': ...}``."""
    fake_store = MagicMock()
    fake_store.append = AsyncMock(return_value="h3")

    proc = AuditProcessor(
        action="x",
        metadata_from="properties.payload",
        outcome="success",
    )
    exchange = _make_exchange(properties={"payload": "raw-string"})

    with patch.object(AuditProcessor, "_build_store", return_value=fake_store):
        await proc.process(exchange, MagicMock())

    kwargs = fake_store.append.await_args.kwargs
    assert kwargs["metadata"] == {"value": "raw-string"}


async def test_audit_outcome_from_expression_overrides_static() -> None:
    """``outcome_from`` имеет приоритет над статическим ``outcome``."""
    fake_store = MagicMock()
    fake_store.append = AsyncMock(return_value="h4")

    proc = AuditProcessor(
        action="order.processed",
        outcome="success",
        outcome_from="properties.outcome",
    )
    exchange = _make_exchange(properties={"outcome": "failure"})

    with patch.object(AuditProcessor, "_build_store", return_value=fake_store):
        await proc.process(exchange, MagicMock())

    assert fake_store.append.await_args.kwargs["outcome"] == "failure"


async def test_audit_outcome_from_invalid_falls_back_to_error() -> None:
    """Если ``outcome_from`` вернул невалидное значение — пишется ``error``."""
    fake_store = MagicMock()
    fake_store.append = AsyncMock(return_value="h5")

    proc = AuditProcessor(
        action="x",
        outcome="success",
        outcome_from="properties.outcome",
    )
    exchange = _make_exchange(properties={"outcome": "weird-value"})

    with patch.object(AuditProcessor, "_build_store", return_value=fake_store):
        await proc.process(exchange, MagicMock())

    assert fake_store.append.await_args.kwargs["outcome"] == "error"


async def test_audit_empty_dynamic_action_fails_exchange() -> None:
    """Если ``action_from`` вернул пусто — exchange.fail()."""
    fake_store = MagicMock()
    fake_store.append = AsyncMock()

    proc = AuditProcessor(action_from="properties.missing", outcome="success")
    exchange = _make_exchange(properties={})

    with patch.object(AuditProcessor, "_build_store", return_value=fake_store):
        await proc.process(exchange, MagicMock())

    assert exchange.status == ExchangeStatus.failed
    assert exchange.error is not None
    assert "AuditProcessor" in exchange.error
    fake_store.append.assert_not_awaited()


async def test_audit_swallows_store_error_into_property() -> None:
    """Ошибка ``store.append`` не валит exchange, пишется в property *_error."""
    fake_store = MagicMock()
    fake_store.append = AsyncMock(side_effect=RuntimeError("db down"))

    proc = AuditProcessor(action="x", outcome="success")
    exchange = _make_exchange()

    with patch.object(AuditProcessor, "_build_store", return_value=fake_store):
        await proc.process(exchange, MagicMock())

    assert exchange.status != ExchangeStatus.failed
    assert "audit_event_hash_error" in exchange.properties
    assert "db down" in exchange.properties["audit_event_hash_error"]


async def test_audit_uses_custom_result_property() -> None:
    """Кастомное ``result_property`` используется при записи hash."""
    fake_store = MagicMock()
    fake_store.append = AsyncMock(return_value="hash-x")

    proc = AuditProcessor(
        action="x", outcome="success", result_property="my_audit_hash"
    )
    exchange = _make_exchange()

    with patch.object(AuditProcessor, "_build_store", return_value=fake_store):
        await proc.process(exchange, MagicMock())

    assert exchange.properties["my_audit_hash"] == "hash-x"


# --------------------------------- to_spec() -----------------------------------


def test_audit_to_spec_minimal() -> None:
    """Минимальный round-trip ``to_spec()`` содержит обязательные поля."""
    proc = AuditProcessor(action="order.created", outcome="success")
    spec = proc.to_spec()

    assert "audit" in spec
    inner = spec["audit"]
    assert inner["action"] == "order.created"
    assert inner["outcome"] == "success"
    assert inner["actor"] == "system"
    assert inner["result_property"] == "audit_event_hash"
    # Опциональные поля не должны попадать в spec, если не заданы.
    assert "action_from" not in inner
    assert "actor_from" not in inner
    assert "resource_from" not in inner
    assert "outcome_from" not in inner
    assert "metadata_from" not in inner
    assert "tenant_id_from" not in inner
    assert "correlation_id_from" not in inner


def test_audit_to_spec_full() -> None:
    """Round-trip ``to_spec()`` со всеми опциональными полями."""
    proc = AuditProcessor(
        action="order.created",
        action_from="properties.act",
        actor="bob",
        actor_from="properties.actor",
        resource_from="properties.res",
        outcome="failure",
        outcome_from="properties.out",
        metadata_from="properties.meta",
        tenant_id_from="properties.tenant",
        correlation_id_from="properties.corr",
        result_property="event_hash",
    )
    spec = proc.to_spec()
    inner = spec["audit"]

    assert inner["action"] == "order.created"
    assert inner["action_from"] == "properties.act"
    assert inner["actor"] == "bob"
    assert inner["actor_from"] == "properties.actor"
    assert inner["resource_from"] == "properties.res"
    assert inner["outcome"] == "failure"
    assert inner["outcome_from"] == "properties.out"
    assert inner["metadata_from"] == "properties.meta"
    assert inner["tenant_id_from"] == "properties.tenant"
    assert inner["correlation_id_from"] == "properties.corr"
    assert inner["result_property"] == "event_hash"


def test_audit_to_spec_roundtrip_reconstruct() -> None:
    """Пересоздание процессора из ``to_spec()`` сохраняет идентичный spec."""
    original = AuditProcessor(
        action_from="properties.act",
        actor="auditor",
        outcome="denied",
        metadata_from="properties.payload",
    )
    spec = original.to_spec()
    inner = spec["audit"]

    reconstructed = AuditProcessor(
        action_from=inner.get("action_from"),
        actor=inner["actor"],
        outcome=inner["outcome"],
        metadata_from=inner.get("metadata_from"),
        result_property=inner["result_property"],
    )
    assert reconstructed.to_spec() == spec
