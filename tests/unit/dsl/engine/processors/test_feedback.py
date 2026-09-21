"""Unit-тесты для FeedbackProcessor (S10 K4 W2)."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from src.backend.dsl.engine.processors.feedback import FeedbackProcessor


class _FakeFeedbackService:
    """In-memory заглушка AIFeedbackService."""

    def __init__(self) -> None:
        self.saved: list[dict[str, Any]] = []
        self.labels: list[dict[str, Any]] = []

    async def save_response(self, **kwargs: Any) -> str:
        self.saved.append(kwargs)
        return f"doc_{len(self.saved)}"

    async def set_feedback(self, **kwargs: Any) -> None:
        self.labels.append(kwargs)


class _FakeMessage:
    """Минимальный in_message stub: body + headers."""

    def __init__(self, body: Any) -> None:
        self.body = body
        self.headers: dict[str, Any] = {}


class _FakeExchange:
    """Минимальный stub Exchange (body + properties + fail)."""

    def __init__(self, body: Any = None) -> None:
        self.body = body
        self.in_message = _FakeMessage(body)
        self.properties: dict[str, Any] = {}
        self._props: dict[str, Any] = self.properties
        self.failed: str | None = None

    def fail(self, reason: str) -> None:
        self.failed = reason

    def set_property(self, key: str, value: Any) -> None:
        self._props[key] = value

    def property(self, key: str, default: Any = None) -> Any:
        return self._props.get(key, default)

    def get_property(self, key: str, default: Any = None) -> Any:
        return self._props.get(key, default)


@pytest.mark.asyncio
async def test_records_feedback_with_static_rating(monkeypatch) -> None:
    fake = _FakeFeedbackService()
    monkeypatch.setattr(FeedbackProcessor, "_build_service", staticmethod(lambda: fake))
    proc = FeedbackProcessor(rating=5)
    exchange = _FakeExchange(body={"x": 1})
    await proc.process(exchange, SimpleNamespace())
    assert exchange.failed is None
    assert len(fake.saved) == 1
    assert fake.saved[0]["query"] == "5"
    assert exchange._props["feedback_doc_id"] == "doc_1"


@pytest.mark.asyncio
async def test_records_feedback_with_label_triggers_set_feedback(monkeypatch) -> None:
    fake = _FakeFeedbackService()
    monkeypatch.setattr(FeedbackProcessor, "_build_service", staticmethod(lambda: fake))
    proc = FeedbackProcessor(rating="positive", comment="отлично")
    exchange = _FakeExchange(body="response text")
    await proc.process(exchange, SimpleNamespace())
    assert len(fake.labels) == 1
    assert fake.labels[0]["label"] == "positive"
    assert fake.labels[0]["comment"] == "отлично"


@pytest.mark.asyncio
async def test_fail_on_missing_rating_via_expression(monkeypatch) -> None:
    fake = _FakeFeedbackService()
    monkeypatch.setattr(FeedbackProcessor, "_build_service", staticmethod(lambda: fake))
    proc = FeedbackProcessor(rating_from="body.missing_rating")
    exchange = _FakeExchange(body={"other": "data"})
    await proc.process(exchange, SimpleNamespace())
    assert exchange.failed and "rating" in exchange.failed.lower()
    assert fake.saved == []


def test_constructor_requires_rating_or_rating_from() -> None:
    with pytest.raises(ValueError, match="rating"):
        FeedbackProcessor()


def test_to_spec_round_trip_minimal() -> None:
    proc = FeedbackProcessor(rating="positive")
    spec = proc.to_spec()
    assert "record_feedback" in spec
    body = spec["record_feedback"]
    assert body["rating"] == "positive"
    assert body["agent_id"] == "route_feedback"


def test_to_spec_full_round_trip() -> None:
    proc = FeedbackProcessor(
        rating_from="body.rating",
        comment_from="body.comment",
        route_run_id_from="correlation_id",
        agent_id="my_agent",
    )
    spec = proc.to_spec()["record_feedback"]
    assert spec["rating_from"] == "body.rating"
    assert spec["comment_from"] == "body.comment"
    assert spec["route_run_id_from"] == "correlation_id"
    assert spec["agent_id"] == "my_agent"


@pytest.mark.asyncio
async def test_error_in_save_recorded_as_property(monkeypatch) -> None:
    class _Boom:
        async def save_response(self, **kw: Any) -> str:
            raise RuntimeError("DB down")

    monkeypatch.setattr(
        FeedbackProcessor, "_build_service", staticmethod(lambda: _Boom())
    )
    proc = FeedbackProcessor(rating=3)
    exchange = _FakeExchange(body={"x": 1})
    await proc.process(exchange, SimpleNamespace())
    assert "DB down" in exchange._props["feedback_doc_id_error"]
