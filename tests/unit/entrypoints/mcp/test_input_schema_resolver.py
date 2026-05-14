"""Smoke-тесты для модуля input_schema_resolver (K4 Sprint-3 Wave 2).

Проверяет:
    - resolve_input_schema генерирует JSON-Schema из Pydantic-модели;
    - resolve_input_schema возвращает пустую схему при отсутствии модели;
    - validate_input_schema принимает корректный payload;
    - validate_input_schema отклоняет некорректный payload;
    - resolve_input_schema включает required-поля из Pydantic-модели.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from pydantic import BaseModel

# ── Тестовые Pydantic-модели ──────────────────────────────────────────────


class _CreditPayload(BaseModel):
    """Тестовая payload-модель для кредитного action."""

    client_id: str
    amount: float
    currency: str = "RUB"


class _OrderPayload(BaseModel):
    """Тестовая payload-модель с обязательными полями."""

    order_id: str
    items: list[str]
    total: float


# ── Вспомогательный stub ActionSpec ──────────────────────────────────────


@dataclass
class _ActionSpecStub:
    """Минимальный stub ActionSpec для тестов (без зависимости от entrypoints)."""

    name: str
    body_model: type[BaseModel] | None = None
    response_model: type[BaseModel] | None = None
    description: str | None = None
    action_id: str | None = None


# ── Тест 1: resolve_pydantic_model_to_jsonschema ──────────────────────────


def test_resolve_pydantic_model_to_jsonschema() -> None:
    """resolve_input_schema генерирует JSON-Schema из Pydantic body_model."""
    from src.backend.entrypoints.mcp.input_schema_resolver import (
        ResolvedToolSchema,
        resolve_input_schema,
    )

    spec = _ActionSpecStub(name="credit.check", body_model=_CreditPayload)
    result = resolve_input_schema(spec)

    assert isinstance(result, ResolvedToolSchema)
    assert result.name == "credit_check"
    # JSON-Schema должна содержать properties
    assert "properties" in result.input_schema
    assert "client_id" in result.input_schema["properties"]
    assert "amount" in result.input_schema["properties"]
    assert "currency" in result.input_schema["properties"]


# ── Тест 2: resolve_handles_no_model ─────────────────────────────────────


def test_resolve_handles_no_model() -> None:
    """resolve_input_schema возвращает пустую схему при отсутствии params model."""
    from src.backend.entrypoints.mcp.input_schema_resolver import resolve_input_schema

    spec = _ActionSpecStub(name="system.health", body_model=None)
    result = resolve_input_schema(spec)

    assert result.input_schema == {}
    assert result.output_schema == {}
    # name корректно сформирован
    assert result.name == "system_health"


# ── Тест 3: validate_accepts_valid_payload ────────────────────────────────


def test_validate_accepts_valid_payload() -> None:
    """validate_input_schema возвращает (True, None) для корректного payload."""
    from src.backend.entrypoints.mcp.input_schema_resolver import (
        resolve_input_schema,
        validate_input_schema,
    )

    spec = _ActionSpecStub(name="order.create", body_model=_OrderPayload)
    resolved = resolve_input_schema(spec)

    valid_payload: dict[str, Any] = {
        "order_id": "ORD-001",
        "items": ["item_a", "item_b"],
        "total": 1250.50,
    }

    ok, error = validate_input_schema(resolved.input_schema, valid_payload, strict=False)

    assert ok is True
    assert error is None


# ── Тест 4: validate_rejects_invalid_payload ──────────────────────────────


def test_validate_rejects_invalid_payload() -> None:
    """validate_input_schema возвращает (False, msg) для некорректного payload."""
    from src.backend.entrypoints.mcp.input_schema_resolver import (
        resolve_input_schema,
        validate_input_schema,
    )

    spec = _ActionSpecStub(name="order.create", body_model=_OrderPayload)
    resolved = resolve_input_schema(spec)

    # Пропускаем обязательное поле order_id
    invalid_payload: dict[str, Any] = {
        "items": ["item_a"],
        "total": 99.99,
    }

    ok, error = validate_input_schema(resolved.input_schema, invalid_payload, strict=False)

    assert ok is False
    assert error is not None
    assert isinstance(error, str)
    assert len(error) > 0


# ── Тест 5: resolve_includes_required_fields ─────────────────────────────


def test_resolve_includes_required_fields() -> None:
    """resolve_input_schema корректно помечает обязательные поля в JSON-Schema."""
    from src.backend.entrypoints.mcp.input_schema_resolver import resolve_input_schema

    spec = _ActionSpecStub(name="credit.apply", body_model=_CreditPayload)
    result = resolve_input_schema(spec)

    schema = result.input_schema
    assert "required" in schema
    # client_id и amount обязательны; currency имеет default — не обязательно
    required_fields: list[str] = schema["required"]
    assert "client_id" in required_fields
    assert "amount" in required_fields
    # currency имеет default="RUB" → не в required
    assert "currency" not in required_fields
