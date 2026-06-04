"""Бенчмарк msgspec.Struct vs Pydantic BaseModel на hotpath сериализации.

Wave ``[wave:s6/msgspec-benchmark]``. Цель — собрать заранее объективные
числа, чтобы перед массовой миграцией Sprint 6 принять решение о
переключении hotpath с Pydantic на msgspec.Struct.

Замеряемые операции (типичные для проекта):

* **response.serialize** — крупный DTO ответа REST (~10 полей, nested).
* **event.broadcast** — компактный event payload (~5 полей) ×100 элементов.

Запуск (требует extra ``perf``)::

    uv pip install -e .[perf]
    pytest tests/perf/test_msgspec_benchmark.py --benchmark-only

Отчёт сохраняется в ``vault/benchmark-2026-05-14-msgspec.md``.
"""

# ruff: noqa: S101

from __future__ import annotations

from typing import Any

import msgspec
import pytest
from pydantic import BaseModel


# ── Pydantic-модели ──


class PydanticAddress(BaseModel):
    """Адрес — вложенная Pydantic-модель."""

    street: str
    city: str
    zip: str


class PydanticResponseDTO(BaseModel):
    """Большой DTO ответа REST (10 полей, 1 nested)."""

    id: int
    name: str
    email: str
    age: int
    is_active: bool
    address: PydanticAddress
    tags: list[str]
    score: float
    payload: dict[str, Any]
    notes: str | None = None


class PydanticEvent(BaseModel):
    """Компактный event payload для broadcaster (5 полей)."""

    event_id: str
    type: str
    timestamp: float
    user_id: int
    data: dict[str, Any]


# ── msgspec-структуры ──


class MsgspecAddress(msgspec.Struct):
    street: str
    city: str
    zip: str


class MsgspecResponseDTO(msgspec.Struct):
    id: int
    name: str
    email: str
    age: int
    is_active: bool
    address: MsgspecAddress
    tags: list[str]
    score: float
    payload: dict[str, Any]
    notes: str | None = None


class MsgspecEvent(msgspec.Struct):
    event_id: str
    type: str
    timestamp: float
    user_id: int
    data: dict[str, Any]


# ── Фикстуры ──

SAMPLE_RESPONSE = {
    "id": 42,
    "name": "Иван Петров",
    "email": "ivan@example.com",
    "age": 33,
    "is_active": True,
    "address": {"street": "Невский 100", "city": "СПб", "zip": "190000"},
    "tags": ["vip", "lead", "credit"],
    "score": 0.83,
    "payload": {"source": "api", "version": 2},
    "notes": None,
}

SAMPLE_EVENT = {
    "event_id": "evt-123",
    "type": "order.created",
    "timestamp": 1715670000.0,
    "user_id": 42,
    "data": {"amount": 1500, "currency": "RUB"},
}


# ── Pydantic bench ──


@pytest.mark.benchmark(group="serialize_response_dto")
def test_pydantic_response_dto_serialize(benchmark: Any) -> None:
    """Pydantic .model_dump_json для response DTO."""
    model = PydanticResponseDTO.model_validate(SAMPLE_RESPONSE)
    benchmark(model.model_dump_json)


@pytest.mark.benchmark(group="serialize_response_dto")
def test_msgspec_response_dto_serialize(benchmark: Any) -> None:
    """msgspec.json.encode для response DTO."""
    model = msgspec.convert(SAMPLE_RESPONSE, type=MsgspecResponseDTO)
    encoder = msgspec.json.Encoder()
    benchmark(encoder.encode, model)


# ── Event broadcaster bench ──


@pytest.mark.benchmark(group="serialize_event_x100")
def test_pydantic_event_batch_serialize(benchmark: Any) -> None:
    """Pydantic пакетная сериализация 100 events."""
    events = [PydanticEvent.model_validate(SAMPLE_EVENT) for _ in range(100)]

    def _run() -> list[str]:
        return [e.model_dump_json() for e in events]

    benchmark(_run)


@pytest.mark.benchmark(group="serialize_event_x100")
def test_msgspec_event_batch_serialize(benchmark: Any) -> None:
    """msgspec пакетная сериализация 100 events."""
    events = [msgspec.convert(SAMPLE_EVENT, type=MsgspecEvent) for _ in range(100)]
    encoder = msgspec.json.Encoder()

    def _run() -> list[bytes]:
        return [encoder.encode(e) for e in events]

    benchmark(_run)


# ── Deserialization bench (parsing) ──


SAMPLE_RESPONSE_JSON = msgspec.json.encode(SAMPLE_RESPONSE)


@pytest.mark.benchmark(group="parse_response_dto")
def test_pydantic_response_dto_parse(benchmark: Any) -> None:
    """Pydantic парсинг JSON → модель."""
    benchmark(PydanticResponseDTO.model_validate_json, SAMPLE_RESPONSE_JSON)


@pytest.mark.benchmark(group="parse_response_dto")
def test_msgspec_response_dto_parse(benchmark: Any) -> None:
    """msgspec парсинг JSON → структура."""
    decoder = msgspec.json.Decoder(MsgspecResponseDTO)
    benchmark(decoder.decode, SAMPLE_RESPONSE_JSON)
