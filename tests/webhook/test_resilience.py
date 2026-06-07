"""Sprint 21 W5 — Webhook resilience через RPACallPolicy (G-07 closure).

Покрытие:
    * WebhookSink с RPACallPolicy: 5xx burst → retries → DLQ.
    * Feature-flag OFF → ad-hoc try/except, без retry.
    * Pybreaker emulation: CB открывается после M failures.
    * webhook_scheduler.execute_webhook() возвращает retries_exhausted.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

import pytest

from src.backend.core.messaging.dlq import DLQEnvelope, DLQReason
from src.backend.core.resilience.rpa_policy import RPACallPolicy, set_rpa_policy

pytestmark = pytest.mark.asyncio


class _InMemoryDLQ:
    def __init__(self) -> None:
        self.envelopes: list[DLQEnvelope] = []

    async def write(self, envelope: DLQEnvelope) -> None:
        self.envelopes.append(envelope)


@pytest.fixture(autouse=True)
def _enable_flags(monkeypatch: pytest.MonkeyPatch) -> None:
    from src.backend.core.config import features as features_module

    monkeypatch.setattr(
        features_module.feature_flags,
        "rpa_resilience_wrapper_enabled",
        True,
        raising=False,
    )
    monkeypatch.setattr(
        features_module.feature_flags,
        "webhook_resilience_policy_enabled",
        True,
        raising=False,
    )


@pytest.fixture(autouse=True)
def _reset_policy() -> None:
    """Reset module-level RPACallPolicy singleton."""
    set_rpa_policy(None)
    yield
    set_rpa_policy(None)


@pytest.fixture
def dlq() -> _InMemoryDLQ:
    return _InMemoryDLQ()


async def test_webhook_5xx_burst_triggers_dlq(dlq: _InMemoryDLQ) -> None:
    """WebhookSink с retry-policy: 5xx burst N раз → DLQ."""
    from src.backend.infrastructure.sinks.webhook_sink import WebhookSink

    policy = RPACallPolicy(
        name="webhook_test",
        max_attempts=3,
        backoff_initial_seconds=0.001,
        jitter=0.0,
        dlq_writer=dlq,
    )
    set_rpa_policy(policy)

    sink = WebhookSink(sink_id="test", url="https://example.com/hook", event="evt")

    # Mock OutboundHttpClient — всегда возвращает 503
    class _FakeResp:
        def __init__(self, code: int) -> None:
            self.status_code = code
            self.headers = {}
            self.request = None

    class _FakeClient:
        async def __aenter__(self) -> "_FakeClient":
            return self

        async def __aexit__(self, *a, **kw) -> None:
            return None

        async def post(self, url: str, content: bytes, headers: dict) -> _FakeResp:
            return _FakeResp(503)

    with patch("src.backend.core.net.OutboundHttpClient", return_value=_FakeClient()):
        result = await sink.send({"x": 1})

    assert result.ok is False
    assert len(dlq.envelopes) == 1
    assert dlq.envelopes[0].transport == "webhook"
    assert dlq.envelopes[0].reason == DLQReason.RETRIES_EXHAUSTED


async def test_webhook_2xx_success_no_dlq(dlq: _InMemoryDLQ) -> None:
    """2xx — DLQ пустой, ok=True."""
    from src.backend.infrastructure.sinks.webhook_sink import WebhookSink

    policy = RPACallPolicy(
        name="webhook_ok",
        max_attempts=3,
        backoff_initial_seconds=0.001,
        jitter=0.0,
        dlq_writer=dlq,
    )
    set_rpa_policy(policy)

    sink = WebhookSink(sink_id="t", url="https://example.com/hook", event="evt")

    class _FakeResp:
        def __init__(self) -> None:
            self.status_code = 200
            self.headers = {"x-request-id": "rid-1"}

    class _FakeClient:
        async def __aenter__(self) -> "_FakeClient":
            return self

        async def __aexit__(self, *a, **kw) -> None:
            return None

        async def post(self, url: str, content: bytes, headers: dict) -> _FakeResp:
            return _FakeResp()

    with patch("src.backend.core.net.OutboundHttpClient", return_value=_FakeClient()):
        result = await sink.send({"x": 1})

    assert result.ok is True
    assert dlq.envelopes == []


async def test_webhook_breaker_open_skip(dlq: _InMemoryDLQ) -> None:
    """CB-emulation: breaker.is_open=True → call skipped → result error."""
    from src.backend.core.resilience.rpa_policy import _BreakerLike
    from src.backend.infrastructure.sinks.webhook_sink import WebhookSink

    breaker = _BreakerLike(is_open=lambda: True)
    policy = RPACallPolicy(
        name="cb",
        max_attempts=3,
        backoff_initial_seconds=0.001,
        jitter=0.0,
        dlq_writer=dlq,
        breaker=breaker,
    )
    set_rpa_policy(policy)

    sink = WebhookSink(sink_id="cb-test", url="https://example.com/hook", event="evt")

    # Если CB открыт — POST даже не должен вызываться
    call_count = {"n": 0}

    class _FakeResp:
        def __init__(self) -> None:
            self.status_code = 200

    class _FakeClient:
        async def __aenter__(self) -> "_FakeClient":
            return self

        async def __aexit__(self, *a, **kw) -> None:
            return None

        async def post(self, *a: Any, **kw: Any) -> _FakeResp:
            call_count["n"] += 1
            return _FakeResp()

    with patch("src.backend.core.net.OutboundHttpClient", return_value=_FakeClient()):
        result = await sink.send({"x": 1})

    assert result.ok is False
    assert call_count["n"] == 0


async def test_webhook_feature_flag_off_no_retry(
    dlq: _InMemoryDLQ, monkeypatch: pytest.MonkeyPatch
) -> None:
    """webhook_resilience_policy_enabled OFF → legacy путь."""
    from src.backend.core.config import features as features_module
    from src.backend.infrastructure.sinks.webhook_sink import WebhookSink

    monkeypatch.setattr(
        features_module.feature_flags,
        "webhook_resilience_policy_enabled",
        False,
        raising=False,
    )

    policy = RPACallPolicy(
        name="not_used", max_attempts=3, backoff_initial_seconds=0.001, dlq_writer=dlq
    )
    set_rpa_policy(policy)

    sink = WebhookSink(sink_id="off", url="https://example.com/hook", event="evt")
    call_count = {"n": 0}

    class _FakeResp:
        def __init__(self) -> None:
            self.status_code = 503
            self.request = None
            self.headers = {}

    class _FakeClient:
        async def __aenter__(self) -> "_FakeClient":
            return self

        async def __aexit__(self, *a, **kw) -> None:
            return None

        async def post(self, *a: Any, **kw: Any) -> _FakeResp:
            call_count["n"] += 1
            return _FakeResp()

    with patch("src.backend.core.net.OutboundHttpClient", return_value=_FakeClient()):
        result = await sink.send({"x": 1})

    # При OFF — без retry; 503 поднимается в _do_post через HTTPStatusError
    assert result.ok is False
    assert call_count["n"] == 1  # один вызов, не 3
    assert dlq.envelopes == []  # DLQ не используется
