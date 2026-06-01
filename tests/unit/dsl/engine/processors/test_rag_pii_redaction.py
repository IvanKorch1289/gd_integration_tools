"""Тесты Sprint 11 K1 W1 — RAG PII redaction processor."""

from __future__ import annotations

from typing import Any

import pytest

from src.backend.dsl.engine.processors.ai import RagPIIRedactionProcessor
from src.backend.services.ai.pii.retrieval_masker import (
    mask_augment_result,
    mask_retrieval_documents,
)


class _Exchange:
    """Минимальный exchange-stub: только properties dict."""

    def __init__(self, properties: dict[str, Any] | None = None) -> None:
        self.properties = properties or {}
        self.in_message = type("M", (), {})()

    def set_property(self, key: str, value: Any) -> None:
        self.properties[key] = value


class _Context:
    """Stub ExecutionContext — процессор не пользуется им напрямую."""


def test_mask_retrieval_documents_redacts_email_and_phone() -> None:
    """Email и phone в document.content маскируются на ***."""
    docs = [
        {"content": "Свяжитесь: alice@example.com или +7 999 123-45-67"},
        {"content": "Без PII"},
    ]
    masked = mask_retrieval_documents(docs)
    assert "alice@example.com" not in masked[0]["content"]
    assert "+7 999" not in masked[0]["content"]
    assert masked[1]["content"] == "Без PII"


def test_mask_augment_result_covers_documents_and_citations() -> None:
    """``documents[*].content`` + ``citations[*].content`` + ``prompt`` маскируются."""
    payload = {
        "prompt": "User: my CC is 4111-1111-1111-1111",
        "documents": [{"content": "SSN 123-45-6789"}],
        "citations": [{"content": "Email: bob@x.io"}],
    }
    masked = mask_augment_result(payload)
    assert "4111-1111" not in masked["prompt"]
    assert "123-45-6789" not in masked["documents"][0]["content"]
    assert "bob@x.io" not in masked["citations"][0]["content"]


@pytest.mark.asyncio
async def test_processor_passthrough_when_flag_off(monkeypatch: pytest.MonkeyPatch) -> None:
    """При ``rag_pii_retrieval_mask=False`` payload остаётся без изменений."""
    from src.backend.core.config import features as features_module

    monkeypatch.setattr(features_module.feature_flags, "rag_pii_retrieval_mask", False)
    payload = {"prompt": "Email me at bob@x.io"}
    exchange = _Exchange(properties={"augment_result": payload})
    processor = RagPIIRedactionProcessor(input_property="augment_result")

    await processor.process(exchange, _Context())

    assert exchange.properties["augment_result"]["prompt"] == "Email me at bob@x.io"


@pytest.mark.asyncio
async def test_processor_redacts_when_flag_on(monkeypatch: pytest.MonkeyPatch) -> None:
    """При ``rag_pii_retrieval_mask=True`` PII в documents → ***."""
    from src.backend.core.config import features as features_module

    monkeypatch.setattr(features_module.feature_flags, "rag_pii_retrieval_mask", True)
    payload = {
        "prompt": "Q: what is my card?",
        "documents": [{"content": "Card 4111 1111 1111 1111 belongs to Alice"}],
        "citations": [{"content": "Phone +7-999-123-45-67"}],
    }
    exchange = _Exchange(properties={"augment_result": payload})
    processor = RagPIIRedactionProcessor(input_property="augment_result")

    await processor.process(exchange, _Context())

    masked = exchange.properties["augment_result"]
    assert "4111" not in masked["documents"][0]["content"]
    assert "+7-999" not in masked["citations"][0]["content"]
