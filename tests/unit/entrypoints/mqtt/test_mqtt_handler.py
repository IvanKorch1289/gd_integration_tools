"""Unit tests for MqttHandler."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.backend.entrypoints.mqtt.mqtt_handler import MqttHandler, MqttSettings


class TestMqttSettings:
    """Tests for :class:`MqttSettings`."""

    def test_defaults(self) -> None:
        s = MqttSettings(broker_host="localhost", broker_port=1883)
        assert s.broker_host == "localhost"
        assert s.broker_port == 1883
        assert s.enabled is False
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
            "src.backend.entrypoints.mqtt.mqtt_handler.get_task_registry"
        ) as mock_reg:
            await handler.start()
        mock_reg.assert_not_called()

    @pytest.mark.asyncio
    async def test_stop_cancels_task(self, handler: MqttHandler) -> None:
        handler._running = True
        task = AsyncMock()
        task.done.return_value = False
        task.cancel = MagicMock()
        handler._task = task
        await handler.stop()
        assert handler._running is False
        assert task.cancel.called

    @pytest.mark.asyncio
    async def test_handle_message_with_action(self, handler: MqttHandler) -> None:
        mock_registry = AsyncMock()
        with patch(
            "src.backend.dsl.commands.registry.action_handler_registry",
            mock_registry,
        ):
            await handler._handle_message(
                "gd/orders/create", b'{"action":"orders.create","id":1}'
            )
        mock_registry.dispatch.assert_awaited_once()
        call = mock_registry.dispatch.await_args[0][0]
        assert call.action == "orders.create"

    @pytest.mark.asyncio
    async def test_handle_message_falls_back_to_topic(self, handler: MqttHandler) -> None:
        mock_registry = AsyncMock()
        with patch(
            "src.backend.dsl.commands.registry.action_handler_registry",
            mock_registry,
        ):
            await handler._handle_message("gd/orders/create", b'{"id":1}')
        call = mock_registry.dispatch.await_args[0][0]
        assert call.action == "orders.create"

    @pytest.mark.asyncio
    async def test_handle_message_invalid_json(self, handler: MqttHandler) -> None:
        mock_registry = AsyncMock()
        with patch(
            "src.backend.dsl.commands.registry.action_handler_registry",
            mock_registry,
        ):
            await handler._handle_message("gd/orders/create", b"not-json")
        mock_registry.dispatch.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_handle_message_unregistered_action(self, handler: MqttHandler) -> None:
        mock_registry = AsyncMock()
        mock_registry.dispatch.side_effect = KeyError("nope")
        with patch(
            "src.backend.dsl.commands.registry.action_handler_registry",
            mock_registry,
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
