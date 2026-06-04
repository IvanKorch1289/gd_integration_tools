# ruff: noqa: S101
"""Тесты ``RedisFeatureFlagBroadcaster`` (Sprint 17 K5 W1 / D9).

Покрывают:

* serialize / deserialize round-trip;
* publish успех + failure (счётчики);
* subscriber применяет foreign-replica messages;
* subscriber игнорирует own-replica echo;
* malformed payload не валит loop;
* maybe_start_broadcaster — graceful no-op при выключенном FF / None Redis.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any

import pytest

from src.backend.core.feature_flags.redis_broadcaster import (
    BROADCAST_CHANNEL,
    RedisFeatureFlagBroadcaster,
    _set_replica_id_for_tests,
    deserialize_change,
    maybe_start_broadcaster,
    serialize_change,
)
from src.backend.core.feature_flags.runtime_overrides import (
    FeatureFlagChange,
    RuntimeFeatureFlagOverrides,
)


def _make_change(
    *, flag: str = "test_flag", tenant_id: str | None = None, new_value: Any = True
) -> FeatureFlagChange:
    return FeatureFlagChange(
        flag=flag,
        tenant_id=tenant_id,
        old_value=None,
        new_value=new_value,
        actor="test",
        timestamp=datetime(2026, 5, 22, 18, 0, tzinfo=timezone.utc),
    )


class _FakeRedis:
    """Async Redis stub только для publish() + pubsub()."""

    def __init__(self) -> None:
        self.published: list[tuple[str, bytes]] = []
        self.fail_publish = False
        self.pubsub_instance: _FakePubSub | None = None

    async def publish(self, channel: str, payload: bytes) -> int:
        if self.fail_publish:
            raise RuntimeError("redis offline")
        self.published.append((channel, payload))
        return 1

    def pubsub(self) -> "_FakePubSub":
        self.pubsub_instance = _FakePubSub()
        return self.pubsub_instance


class _FakePubSub:
    """Pub/sub stub с управляемой очередью messages."""

    def __init__(self) -> None:
        self.messages: list[dict[str, Any]] = []
        self.subscribed_channels: list[str] = []
        self.closed = False
        self._iter_done = asyncio.Event()

    async def subscribe(self, channel: str) -> None:
        self.subscribed_channels.append(channel)

    async def unsubscribe(self, channel: str) -> None:
        if channel in self.subscribed_channels:
            self.subscribed_channels.remove(channel)

    async def aclose(self) -> None:
        self.closed = True

    async def listen(self):  # type: ignore[no-untyped-def]
        for msg in self.messages:
            yield msg
        # Ждём пока тест не отменит — listen-loop обычно бесконечный.
        await self._iter_done.wait()


# ─── Serialize / deserialize ────────────────────────────────────────


class TestSerialization:
    def test_round_trip_preserves_fields(self) -> None:
        change = _make_change(flag="x", tenant_id="t1", new_value="val")
        payload = serialize_change(change)
        decoded = deserialize_change(payload)
        assert decoded["flag"] == "x"
        assert decoded["tenant_id"] == "t1"
        assert decoded["new_value"] == "val"
        assert decoded["actor"] == "test"
        assert "source_replica" in decoded
        assert "timestamp" in decoded


# ─── Publish ────────────────────────────────────────────────────────


class TestPublish:
    @pytest.mark.asyncio
    async def test_publish_success_increments_counter(self) -> None:
        overrides = RuntimeFeatureFlagOverrides()
        redis = _FakeRedis()
        bcast = RedisFeatureFlagBroadcaster(redis_client=redis, overrides=overrides)
        ok = await bcast.publish(_make_change())
        assert ok is True
        assert bcast.state.publish_total == 1
        assert bcast.state.publish_errors_total == 0
        assert len(redis.published) == 1
        assert redis.published[0][0] == BROADCAST_CHANNEL

    @pytest.mark.asyncio
    async def test_publish_failure_increments_error_counter(self) -> None:
        overrides = RuntimeFeatureFlagOverrides()
        redis = _FakeRedis()
        redis.fail_publish = True
        bcast = RedisFeatureFlagBroadcaster(redis_client=redis, overrides=overrides)
        ok = await bcast.publish(_make_change())
        assert ok is False
        assert bcast.state.publish_total == 0
        assert bcast.state.publish_errors_total == 1


# ─── Subscriber message application ─────────────────────────────────


class TestSubscriber:
    @pytest.mark.asyncio
    async def test_foreign_replica_message_applied(self) -> None:
        """Message от другой replica → override применяется к local singleton."""
        previous = _set_replica_id_for_tests("local-replica")
        try:
            overrides = RuntimeFeatureFlagOverrides()
            redis = _FakeRedis()
            bcast = RedisFeatureFlagBroadcaster(redis_client=redis, overrides=overrides)
            # Pre-fill messages в Fake pubsub до start().
            await bcast.start(
                task_factory=lambda coro, name: asyncio.create_task(coro, name=name)
            )
            assert redis.pubsub_instance is not None
            pubsub = redis.pubsub_instance
            # Подменим listen-сообщения payload'ом от другой replica.
            _set_replica_id_for_tests("local-replica")
            from src.backend.core.feature_flags import redis_broadcaster as mod

            previous2 = mod._PROCESS_REPLICA_ID
            mod._PROCESS_REPLICA_ID = "remote-replica"
            foreign_payload = serialize_change(
                _make_change(flag="remote_flag", new_value="from-remote")
            )
            mod._PROCESS_REPLICA_ID = "local-replica"
            pubsub.messages.append({"type": "message", "data": foreign_payload})
            # Дать subscriber-loop'у итерацию.
            await asyncio.sleep(0.05)
            assert bcast.state.received_total >= 1
            assert bcast.state.applied_total >= 1
            assert overrides.get("remote_flag", default=None) == "from-remote"
            mod._PROCESS_REPLICA_ID = previous2
            await bcast.stop()
        finally:
            _set_replica_id_for_tests(previous)

    @pytest.mark.asyncio
    async def test_own_replica_echo_skipped(self) -> None:
        """Message с source_replica == own → не применяется."""
        previous = _set_replica_id_for_tests("local-replica")
        try:
            overrides = RuntimeFeatureFlagOverrides()
            redis = _FakeRedis()
            bcast = RedisFeatureFlagBroadcaster(redis_client=redis, overrides=overrides)
            await bcast.start(
                task_factory=lambda coro, name: asyncio.create_task(coro, name=name)
            )
            pubsub = redis.pubsub_instance
            assert pubsub is not None
            # serialize_change использует current _PROCESS_REPLICA_ID — own.
            own_payload = serialize_change(
                _make_change(flag="echo_flag", new_value="echo-val")
            )
            pubsub.messages.append({"type": "message", "data": own_payload})
            await asyncio.sleep(0.05)
            assert bcast.state.received_total >= 1
            assert bcast.state.echo_skipped_total >= 1
            assert bcast.state.applied_total == 0
            assert overrides.get("echo_flag", default="default-val") == "default-val"
            await bcast.stop()
        finally:
            _set_replica_id_for_tests(previous)

    @pytest.mark.asyncio
    async def test_malformed_payload_does_not_break_loop(self) -> None:
        previous = _set_replica_id_for_tests("local-replica")
        try:
            overrides = RuntimeFeatureFlagOverrides()
            redis = _FakeRedis()
            bcast = RedisFeatureFlagBroadcaster(redis_client=redis, overrides=overrides)
            await bcast.start(
                task_factory=lambda coro, name: asyncio.create_task(coro, name=name)
            )
            pubsub = redis.pubsub_instance
            assert pubsub is not None
            pubsub.messages.append({"type": "message", "data": b"\xff not-json"})
            await asyncio.sleep(0.05)
            # Counter received не растёт через malformed (или растёт без applied)
            assert bcast.state.applied_total == 0
            await bcast.stop()
        finally:
            _set_replica_id_for_tests(previous)

    @pytest.mark.asyncio
    async def test_clear_event_calls_overrides_clear(self) -> None:
        """new_value=None → overrides.clear()."""
        previous = _set_replica_id_for_tests("local-replica")
        try:
            overrides = RuntimeFeatureFlagOverrides()
            overrides.set("flag_to_clear", True, tenant_id=None, actor="setup")
            assert overrides.has_override("flag_to_clear")
            redis = _FakeRedis()
            bcast = RedisFeatureFlagBroadcaster(redis_client=redis, overrides=overrides)
            await bcast.start(
                task_factory=lambda coro, name: asyncio.create_task(coro, name=name)
            )
            pubsub = redis.pubsub_instance
            assert pubsub is not None
            from src.backend.core.feature_flags import redis_broadcaster as mod

            previous2 = mod._PROCESS_REPLICA_ID
            mod._PROCESS_REPLICA_ID = "remote-replica"
            clear_payload = serialize_change(
                FeatureFlagChange(
                    flag="flag_to_clear",
                    tenant_id=None,
                    old_value=True,
                    new_value=None,
                    actor="remote",
                    timestamp=datetime.now(timezone.utc),
                )
            )
            mod._PROCESS_REPLICA_ID = "local-replica"
            pubsub.messages.append({"type": "message", "data": clear_payload})
            await asyncio.sleep(0.05)
            assert not overrides.has_override("flag_to_clear")
            mod._PROCESS_REPLICA_ID = previous2
            await bcast.stop()
        finally:
            _set_replica_id_for_tests(previous)


# ─── maybe_start_broadcaster ────────────────────────────────────────


class TestMaybeStart:
    @pytest.mark.asyncio
    async def test_disabled_flag_returns_none(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from src.backend.core.config import features

        monkeypatch.setattr(features.feature_flags, "tenant_feature_flag_ui", False)
        overrides = RuntimeFeatureFlagOverrides()
        result = await maybe_start_broadcaster(
            redis_client=_FakeRedis(), overrides=overrides
        )
        assert result is None

    @pytest.mark.asyncio
    async def test_none_redis_returns_none(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from src.backend.core.config import features

        monkeypatch.setattr(features.feature_flags, "tenant_feature_flag_ui", True)
        overrides = RuntimeFeatureFlagOverrides()
        result = await maybe_start_broadcaster(redis_client=None, overrides=overrides)
        assert result is None
