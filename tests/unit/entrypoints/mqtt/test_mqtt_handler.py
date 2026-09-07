"""Unit tests for MqttHandler."""

from __future__ import annotations

import asyncio

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.backend.entrypoints.mqtt.mqtt_handler import MqttHandler, MqttSettings


class TestMqttSettings:
    """Tests for :class:`MqttSettings`."""

    def test_defaults(self) -> None:
        s = MqttSettings(broker_host="localhost", broker_port=1883)
        assert s.broker_host == "localhost"
        assert s.broker_port == 1883
        assert s.enabled is True  # S171 M9: default=True (project not in prod)
        assert s.qos == 1
        assert s.topics == ["gd/#"]


class TestMqttHandler:
    """Tests for :class:`MqttHandler`."""

    @pytest.fixture
    def settings(self) -> MqttSettings:
        return MqttSettings(broker_host="broker.local", broker_port=1883, enabled=True)

    @pytest.fixture
    def handler(self, settings: MqttSettings) -> MqttHandler:
        return MqttHandler(settings)

    def test_topic_to_action_basic(self, handler: MqttHandler) -> None:
        assert handler._topic_to_action("gd/orders/create") == "orders.create"

    def test_topic_to_action_multi_level(self, handler: MqttHandler) -> None:
        assert handler._topic_to_action("gd/events/user/login") == "events.user_login"

    def test_topic_to_action_no_prefix(self, handler: MqttHandler) -> None:
        assert handler._topic_to_action("orders/create") == "orders.create"

    def test_topic_to_action_single_part(self, handler: MqttHandler) -> None:
        assert handler._topic_to_action("heartbeat") == "heartbeat"

    def test_topic_to_action_empty(self, handler: MqttHandler) -> None:
        assert handler._topic_to_action("") == ""

    def test_build_tls_context_disabled(self, handler: MqttHandler) -> None:
        assert handler._build_tls_context() is None

    def test_build_tls_context_enabled(self, handler: MqttHandler) -> None:
        handler._settings.tls_enabled = True
        handler._settings.ca_cert_path = "/fake/ca.pem"
        with patch("ssl.create_default_context") as mock_ctx:
            mock_ctx.return_value = MagicMock()
            result = handler._build_tls_context()
        assert result is not None
        mock_ctx.assert_called_once_with(cafile="/fake/ca.pem")

    @pytest.mark.asyncio
    async def test_start_creates_task(self, handler: MqttHandler) -> None:
        mock_registry = MagicMock()
        mock_registry.create_task = MagicMock(return_value=AsyncMock())
        with patch(
            "src.backend.entrypoints.mqtt.mqtt_handler.get_task_registry",
            return_value=mock_registry,
        ):
            await handler.start()
        assert handler._running is True
        mock_registry.create_task.assert_called_once()

    @pytest.mark.asyncio
    async def test_start_disabled(self, handler: MqttHandler) -> None:
        handler._settings.enabled = False
        with patch(
            "src.backend.entrypoints.mqtt.mqtt_handler.get_task_registry",
        ) as mock_reg:
            await handler.start()
        mock_reg.assert_not_called()

    @pytest.mark.asyncio
    async def test_stop_cancels_task(self, handler: MqttHandler) -> None:
        """AsyncMock-квирк (B-NEW-2): done() на AsyncMock возвращал корутину —
        заменяем на явный fake с детерминированным контрактом."""
        handler._running = True

        class _FakeTask:
            def __init__(self) -> None:
                self.cancel_called = False
                self._done = False

            def done(self) -> bool:
                return self._done

            def cancel(self) -> None:
                self.cancel_called = True
                self._done = True

            def __await__(self):  # stop() ждёт task
                async def _noop():
                    return None

                return _noop().__await__()

        fake = _FakeTask()
        handler._task = fake
        await handler.stop()
        assert handler._running is False
        assert fake.cancel_called is True

    @pytest.mark.asyncio
    async def test_handle_message_with_action(self, handler: MqttHandler) -> None:
        mock_registry = AsyncMock()
        with patch(
            "src.backend.core.api.extensions.action_handler_registry", mock_registry,
        ):
            await handler._handle_message(
                "gd/orders/create", b'{"action":"orders.create","id":1}',
            )
        mock_registry.dispatch.assert_awaited_once()
        call = mock_registry.dispatch.await_args[0][0]
        assert call.action == "orders.create"

    @pytest.mark.asyncio
    async def test_handle_message_falls_back_to_topic(
        self, handler: MqttHandler,
    ) -> None:
        mock_registry = AsyncMock()
        with patch(
            "src.backend.core.api.extensions.action_handler_registry", mock_registry,
        ):
            await handler._handle_message("gd/orders/create", b'{"id":1}')
        call = mock_registry.dispatch.await_args[0][0]
        assert call.action == "orders.create"

    @pytest.mark.asyncio
    async def test_handle_message_invalid_json(self, handler: MqttHandler) -> None:
        mock_registry = AsyncMock()
        with patch(
            "src.backend.core.api.extensions.action_handler_registry", mock_registry,
        ):
            await handler._handle_message("gd/orders/create", b"not-json")
        mock_registry.dispatch.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_handle_message_unregistered_action(
        self, handler: MqttHandler,
    ) -> None:
        mock_registry = AsyncMock()
        mock_registry.dispatch.side_effect = KeyError("nope")
        with patch(
            "src.backend.core.api.extensions.action_handler_registry", mock_registry,
        ):
            await handler._handle_message("gd/orders/create", b'{"action":"nope"}')

    @pytest.mark.asyncio
    async def test_publish_success(self, handler: MqttHandler) -> None:
        mock_client = MagicMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.publish = AsyncMock()
        with patch("aiomqtt.Client", return_value=mock_client):
            await handler.publish("gd/test", {"msg": "hello"})
        mock_client.publish.assert_awaited_once()


# ── W3 (ledger): per-message timeout + bounded concurrency ──────────


@pytest.fixture
def handler() -> MqttHandler:
    """Модульный handler для W3-тестов (вне класса TestMqttHandler)."""
    return MqttHandler(MqttSettings(enabled=False))




@pytest.mark.asyncio
async def test_process_message_timeout_does_not_raise(handler: MqttHandler) -> None:
    """Зависший dispatch -> wait_for по message_timeout, без исключения."""
    handler._settings.message_timeout = 0.01

    async def slow_dispatch(command):  # type: ignore[no-untyped-def]
        await asyncio.sleep(1)

    with patch(
        "src.backend.core.api.extensions.action_handler_registry"
    ) as mock_registry:
        mock_registry.dispatch = slow_dispatch
        await handler._process_message(topic="gd/x", payload=b'{"a":1}')
    # исключение не прошло — timeout погашен внутри _process_message


@pytest.mark.asyncio
async def test_process_message_normal_dispatch(handler: MqttHandler) -> None:
    from src.backend.core.api.extensions import action_handler_registry

    with patch.object(
        action_handler_registry,
        "dispatch",
        new=AsyncMock(),
    ) as mock_dispatch:
        await handler._process_message(topic="gd/orders/create", payload=b'{"a":1}')
    mock_dispatch.assert_awaited_once()
    command = mock_dispatch.await_args.args[0]
    assert command.action == "orders.create"


@pytest.mark.asyncio
async def test_stop_cancels_inflight_message_tasks(handler: MqttHandler) -> None:
    """C-P2-2: stop() отменяет in-flight message-задачи поколения."""

    async def sleeper() -> None:
        await asyncio.sleep(30)

    task = asyncio.create_task(sleeper())
    handler._message_tasks.add(task)
    await handler.stop()
    await asyncio.sleep(0)  # дать event-loop применить cancel
    assert task.cancelled() or task.done()


@pytest.mark.asyncio
async def test_publish_success_uses_broker(handler: MqttHandler) -> None:
    """publish через aiomqtt: connect -> publish -> disconnect."""

    class _FakeClient:
        def __init__(self, *a, **k):  # type: ignore[no-untyped-def]
            pass

        async def __aenter__(self):  # type: ignore[no-untyped-def]
            return self

        async def __aexit__(self, *exc):  # type: ignore[no-untyped-def]
            return False

        async def publish(self, topic, payload=None, qos=None):  # type: ignore[no-untyped-def]
            _FakeClient.published = (topic, payload, qos)

    published = {}
    _FakeClient.published = published

    captured: dict[str, object] = {}

    class _RecordingClient(_FakeClient):
        async def publish(self, topic, payload=None, qos=None):  # type: ignore[no-untyped-def]
            captured["topic"] = topic
            captured["payload"] = payload

    with patch("aiomqtt.Client", _RecordingClient):
        await handler.publish("gd/out", {"ok": True})

    assert captured["topic"] == "gd/out"


@pytest.mark.asyncio
async def test_publish_error_swallowed(handler: MqttHandler) -> None:
    """Сбой брокера при publish не роняет вызывающий код."""
    with patch("aiomqtt.Client", side_effect=RuntimeError("broker down")):
        await handler.publish("gd/out", {"ok": True})  # не бросает
