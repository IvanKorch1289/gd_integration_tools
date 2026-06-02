"""T-P0.1.12: unit-тесты для core/resilience/rpa_policy.py (RPACallPolicy).

Coverage: rpa_policy.py 0% → 80%+ через тестирование:
- Dataclasses (RPACallContext, RPACallResult, _BreakerLike)
- RPACallPolicy.__init__ (defaults, validation, jitter clamp)
- dlq_writer property
- call() — passthrough (disabled), breaker open, success, retry success, exhausted, fail-fast
- _send_to_dlq (no writer, with writer, writer fails)
- Module singleton
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.backend.core.messaging.dlq import DLQEnvelope, DLQReason
from src.backend.core.resilience.rpa_policy import (
    RPACallContext,
    RPACallExhausted,
    RPACallPolicy,
    RPACallResult,
    _BreakerLike,
    get_rpa_policy,
    set_rpa_policy,
)


@pytest.fixture(autouse=True)
def _reset_singleton() -> Any:
    """Reset module-level singleton перед каждым тестом."""
    set_rpa_policy(None)
    yield
    set_rpa_policy(None)


class TestExceptions:
    def test_rpa_call_exhausted(self) -> None:
        err = ValueError("boom")
        exc = RPACallExhausted("browser_pool", err)
        assert exc.transport == "browser_pool"
        assert exc.last_error is err
        assert "browser_pool" in str(exc)
        assert "ValueError" in str(exc)
        assert "boom" in str(exc)


class TestDataclasses:
    def test_rpa_call_context_defaults(self) -> None:
        ctx = RPACallContext(transport="cdc")
        assert ctx.transport == "cdc"
        assert ctx.tenant_id is None
        assert ctx.route_id is None
        assert ctx.payload is None
        assert ctx.attempts == 0
        assert ctx.first_failed_at_ts is None
        assert ctx.last_failed_at_ts is None
        assert ctx.last_error is None

    def test_rpa_call_context_with_data(self) -> None:
        payload = {"key": "value"}
        ctx = RPACallContext(
            transport="webhook",
            tenant_id="t1",
            route_id="r1",
            payload=payload,
        )
        assert ctx.payload == {"key": "value"}

    def test_rpa_call_result(self) -> None:
        result = RPACallResult(transport="cdc", attempts=2, duration_seconds=1.5)
        assert result.transport == "cdc"
        assert result.attempts == 2
        assert result.duration_seconds == 1.5

    def test_breaker_like_defaults(self) -> None:
        bl = _BreakerLike()
        assert bl.is_open() is False
        bl.on_success()  # no-op
        bl.on_failure()  # no-op


class TestInit:
    def test_defaults(self) -> None:
        p = RPACallPolicy("test")
        assert p.name == "test"
        assert p.max_attempts == 3
        assert p.backoff_initial == 1.0
        assert p.backoff_max == 30.0
        assert p.jitter == 0.3
        assert p._breaker is None
        assert p._dlq_writer is None
        assert p._on_attempt is None

    def test_max_attempts_validation(self) -> None:
        with pytest.raises(ValueError, match="max_attempts"):
            RPACallPolicy("test", max_attempts=0)

    def test_jitter_clamp_upper(self) -> None:
        p = RPACallPolicy("test", jitter=2.0)
        assert p.jitter == 1.0

    def test_jitter_clamp_lower(self) -> None:
        p = RPACallPolicy("test", jitter=-0.5)
        assert p.jitter == 0.0

    def test_custom_params(self) -> None:
        cb = _BreakerLike()
        p = RPACallPolicy(
            "custom",
            max_attempts=5,
            backoff_initial_seconds=0.5,
            backoff_max_seconds=10.0,
            jitter=0.1,
            breaker=cb,
            retryable_exceptions=(ValueError, KeyError),
        )
        assert p.max_attempts == 5
        assert p.backoff_initial == 0.5
        assert p.backoff_max == 10.0
        assert p._retryable == (ValueError, KeyError)


class TestPropertyDlqWriter:
    def test_none_by_default(self) -> None:
        p = RPACallPolicy("test")
        assert p.dlq_writer is None

    def test_returns_writer(self) -> None:
        writer = MagicMock()
        p = RPACallPolicy("test", dlq_writer=writer)
        assert p.dlq_writer is writer


class TestCallDisabled:
    @pytest.mark.asyncio
    async def test_passthrough_when_disabled(self) -> None:
        """Feature flag OFF (default) — passthrough, без retry/DLQ."""
        # feature_flags.rpa_resilience_wrapper_enabled default = False
        p = RPACallPolicy("test")
        calls = 0

        async def factory() -> str:
            nonlocal calls
            calls += 1
            return "result"

        result = await p.call(factory, transport="cdc")
        assert result == "result"
        assert calls == 1

    @pytest.mark.asyncio
    async def test_passthrough_propagates_exception(self) -> None:
        p = RPACallPolicy("test")

        async def factory() -> None:
            raise ValueError("immediate")

        with pytest.raises(ValueError, match="immediate"):
            await p.call(factory, transport="cdc")


class TestCallEnabled:
    """Тесты с feature_flags.rpa_resilience_wrapper_enabled=True."""

    @pytest.fixture
    def enabled_policy(self) -> RPACallPolicy:
        return RPACallPolicy("test", max_attempts=3)

    @pytest.mark.asyncio
    async def test_breaker_open_raises(
        self, enabled_policy: RPACallPolicy
    ) -> None:
        breaker = _BreakerLike(is_open=lambda: True)
        p = RPACallPolicy("test", breaker=breaker)

        with patch(
            "src.backend.core.resilience.rpa_policy.feature_flags"
        ) as mock_flags:
            mock_flags.rpa_resilience_wrapper_enabled = True
            async def factory() -> str:
                return "should-not-reach"

            with pytest.raises(RPACallExhausted):
                await p.call(factory, transport="cdc")

    @pytest.mark.asyncio
    async def test_success_no_retry(
        self, enabled_policy: RPACallPolicy
    ) -> None:
        calls = 0

        async def factory() -> str:
            nonlocal calls
            calls += 1
            return "ok"

        with patch(
            "src.backend.core.resilience.rpa_policy.feature_flags"
        ) as mock_flags:
            mock_flags.rpa_resilience_wrapper_enabled = True
            result = await enabled_policy.call(factory, transport="cdc")
            assert result == "ok"
            assert calls == 1

    @pytest.mark.asyncio
    async def test_retry_then_success(
        self, enabled_policy: RPACallPolicy
    ) -> None:
        calls = 0

        async def factory() -> str:
            nonlocal calls
            calls += 1
            if calls < 3:
                raise ConnectionError("transient")
            return "ok"

        with patch(
            "src.backend.core.resilience.rpa_policy.feature_flags"
        ) as mock_flags:
            mock_flags.rpa_resilience_wrapper_enabled = True
            with patch(
                "src.backend.core.resilience.rpa_policy.asyncio.sleep"
            ) as mock_sleep:
                result = await enabled_policy.call(factory, transport="cdc")
                assert result == "ok"
                assert calls == 3
                # 2 backoff sleeps (after attempt 1 and 2)
                assert mock_sleep.call_count == 2

    @pytest.mark.asyncio
    async def test_exhausted_raises_and_writes_dlq(
        self, enabled_policy: RPACallPolicy
    ) -> None:
        calls = 0

        async def factory() -> None:
            nonlocal calls
            calls += 1
            raise ConnectionError("never-works")

        writer = AsyncMock()
        p = RPACallPolicy("test", max_attempts=2, dlq_writer=writer)

        with patch(
            "src.backend.core.resilience.rpa_policy.feature_flags"
        ) as mock_flags:
            mock_flags.rpa_resilience_wrapper_enabled = True
            with patch(
                "src.backend.core.resilience.rpa_policy.asyncio.sleep"
            ):
                with pytest.raises(RPACallExhausted):
                    await p.call(
                        factory, transport="cdc", payload={"x": 1}
                    )
                assert calls == 2
                # DLQ write called once
                assert writer.write.call_count == 1
                envelope = writer.write.call_args.args[0]
                assert isinstance(envelope, DLQEnvelope)
                assert envelope.transport == "cdc"
                assert envelope.retry_count == 2

    @pytest.mark.asyncio
    async def test_non_retryable_exception_fail_fast(
        self, enabled_policy: RPACallPolicy
    ) -> None:
        calls = 0

        async def factory() -> None:
            nonlocal calls
            calls += 1
            raise ValueError("non-retryable")

        writer = AsyncMock()
        p = RPACallPolicy(
            "test", max_attempts=5, dlq_writer=writer,
            retryable_exceptions=(ConnectionError,)
        )

        with patch(
            "src.backend.core.resilience.rpa_policy.feature_flags"
        ) as mock_flags:
            mock_flags.rpa_resilience_wrapper_enabled = True
            with pytest.raises(RPACallExhausted):
                await p.call(factory, transport="cdc")
            # ValueError не retryable → fail-fast после 1 попытки
            assert calls == 1
            assert writer.write.call_count == 1

    @pytest.mark.asyncio
    async def test_on_attempt_callback_on_failure(
        self, enabled_policy: RPACallPolicy
    ) -> None:
        attempts_seen: list[tuple[int, BaseException | None]] = []

        def on_attempt(
            ctx: RPACallContext, attempt: int, error: BaseException | None
        ) -> None:
            attempts_seen.append((attempt, error))

        async def factory() -> str:
            raise ConnectionError("fail")

        p = RPACallPolicy("test", max_attempts=1, on_attempt=on_attempt)

        with patch(
            "src.backend.core.resilience.rpa_policy.feature_flags"
        ) as mock_flags:
            mock_flags.rpa_resilience_wrapper_enabled = True
            with pytest.raises(RPACallExhausted):
                await p.call(factory, transport="cdc")
            assert len(attempts_seen) == 1
            assert attempts_seen[0][0] == 0
            assert isinstance(attempts_seen[0][1], ConnectionError)

    @pytest.mark.asyncio
    async def test_on_attempt_callback_on_success(
        self, enabled_policy: RPACallPolicy
    ) -> None:
        attempts_seen: list[tuple[int, BaseException | None]] = []

        def on_attempt(
            ctx: RPACallContext, attempt: int, error: BaseException | None
        ) -> None:
            attempts_seen.append((attempt, error))

        async def factory() -> str:
            return "ok"

        p = RPACallPolicy("test", max_attempts=3, on_attempt=on_attempt)

        with patch(
            "src.backend.core.resilience.rpa_policy.feature_flags"
        ) as mock_flags:
            mock_flags.rpa_resilience_wrapper_enabled = True
            await p.call(factory, transport="cdc")
            assert len(attempts_seen) == 1
            assert attempts_seen[0][0] == 0
            assert attempts_seen[0][1] is None

    @pytest.mark.asyncio
    async def test_on_attempt_callback_failure_does_not_break(
        self, enabled_policy: RPACallPolicy
    ) -> None:
        def bad_callback(
            ctx: RPACallContext, attempt: int, error: BaseException | None
        ) -> None:
            raise RuntimeError("callback-fail")

        async def factory() -> str:
            return "ok"

        p = RPACallPolicy("test", on_attempt=bad_callback)

        with patch(
            "src.backend.core.resilience.rpa_policy.feature_flags"
        ) as mock_flags:
            mock_flags.rpa_resilience_wrapper_enabled = True
            # Callback fails но call() возвращает результат
            result = await p.call(factory, transport="cdc")
            assert result == "ok"

    @pytest.mark.asyncio
    async def test_breaker_on_success_called(
        self, enabled_policy: RPACallPolicy
    ) -> None:
        breaker = _BreakerLike()
        breaker.on_success = MagicMock()
        breaker.on_failure = MagicMock()

        async def factory() -> str:
            return "ok"

        p = RPACallPolicy("test", breaker=breaker)

        with patch(
            "src.backend.core.resilience.rpa_policy.feature_flags"
        ) as mock_flags:
            mock_flags.rpa_resilience_wrapper_enabled = True
            await p.call(factory, transport="cdc")
            breaker.on_success.assert_called_once()
            breaker.on_failure.assert_not_called()

    @pytest.mark.asyncio
    async def test_breaker_on_failure_called(
        self, enabled_policy: RPACallPolicy
    ) -> None:
        breaker = _BreakerLike()
        breaker.on_success = MagicMock()
        breaker.on_failure = MagicMock()

        async def factory() -> None:
            raise ConnectionError("boom")

        p = RPACallPolicy("test", max_attempts=1, breaker=breaker)

        with patch(
            "src.backend.core.resilience.rpa_policy.feature_flags"
        ) as mock_flags:
            mock_flags.rpa_resilience_wrapper_enabled = True
            with pytest.raises(RPACallExhausted):
                await p.call(factory, transport="cdc")
            breaker.on_failure.assert_called_once()
            breaker.on_success.assert_not_called()


class TestSendToDlq:
    @pytest.mark.asyncio
    async def test_no_writer_returns_silently(self) -> None:
        p = RPACallPolicy("test")
        ctx = RPACallContext(transport="cdc", payload="x")
        # Метод private, но доступен
        await p._send_to_dlq(ctx, DLQReason.RETRIES_EXHAUSTED)  # type: ignore[attr-defined]

    @pytest.mark.asyncio
    async def test_writer_called_with_envelope(self) -> None:
        writer = AsyncMock()
        p = RPACallPolicy("test", dlq_writer=writer)
        ctx = RPACallContext(
            transport="webhook",
            tenant_id="t1",
            route_id="r1",
            payload={"key": "val"},
        )
        ctx.last_error = ValueError("oops")
        ctx.attempts = 3
        ctx.first_failed_at_ts = 100.0
        ctx.last_failed_at_ts = 200.0

        await p._send_to_dlq(ctx, DLQReason.RETRIES_EXHAUSTED)  # type: ignore[attr-defined]

        assert writer.write.call_count == 1
        envelope = writer.write.call_args.args[0]
        assert envelope.transport == "webhook"
        assert envelope.tenant_id == "t1"
        assert envelope.route_id == "r1"
        assert envelope.original_payload == {"key": "val"}
        assert envelope.error_class == "ValueError"
        assert envelope.error_message == "oops"
        assert envelope.retry_count == 3
        assert envelope.reason == DLQReason.RETRIES_EXHAUSTED
        assert envelope.metadata == {"policy": "test"}

    @pytest.mark.asyncio
    async def test_writer_failure_logged_not_raised(self) -> None:
        writer = AsyncMock()
        writer.write.side_effect = RuntimeError("dlq-down")
        p = RPACallPolicy("test", dlq_writer=writer)
        ctx = RPACallContext(transport="cdc")

        # Должно залогировать, не raise
        await p._send_to_dlq(ctx, DLQReason.RETRIES_EXHAUSTED)  # type: ignore[attr-defined]


class TestModuleSingleton:
    def test_get_none_by_default(self) -> None:
        assert get_rpa_policy() is None

    def test_set_and_get(self) -> None:
        p = RPACallPolicy("test")
        set_rpa_policy(p)
        assert get_rpa_policy() is p

    def test_set_none_resets(self) -> None:
        p = RPACallPolicy("test")
        set_rpa_policy(p)
        set_rpa_policy(None)
        assert get_rpa_policy() is None


class TestAllExports:
    def test_all(self) -> None:
        from src.backend.core.resilience import rpa_policy as m

        assert set(m.__all__) == {
            "RPACallPolicy",
            "RPACallResult",
            "RPACallExhausted",
            "RPACallContext",
            "get_rpa_policy",
            "set_rpa_policy",
        }
