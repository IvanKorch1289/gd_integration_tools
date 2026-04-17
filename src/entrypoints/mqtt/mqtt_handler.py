"""MQTT-интеграция для IoT и event-driven сценариев.

Подписывается на MQTT-топики и маршрутизирует сообщения
через DSL Engine или ActionHandlerRegistry.

Требует: pip install aiomqtt

Конфигурация через MqttSettings:
    MQTT_BROKER_HOST=broker.local
    MQTT_BROKER_PORT=1883
    MQTT_USERNAME=app
    MQTT_PASSWORD=secret
    MQTT_TOPICS=["gd/orders/#", "gd/events/#"]
"""

import asyncio
import logging
from typing import Any, ClassVar

from pydantic import Field
from pydantic_settings import SettingsConfigDict

from app.core.config.config_loader import BaseSettingsWithLoader

__all__ = ("MqttSettings", "MqttHandler", "get_mqtt_handler")

logger = logging.getLogger("mqtt")


class MqttSettings(BaseSettingsWithLoader):
    """Настройки MQTT-брокера."""

    yaml_group: ClassVar[str] = "mqtt"
    model_config = SettingsConfigDict(env_prefix="MQTT_", extra="forbid")

    broker_host: str = Field(
        default="localhost",
        description="Хост MQTT-брокера",
    )
    broker_port: int = Field(
        default=1883,
        ge=1,
        le=65535,
        description="Порт MQTT-брокера",
    )
    username: str = Field(default="", description="Имя пользователя")
    password: str = Field(default="", description="Пароль")
    client_id: str = Field(
        default="gd-integration-tools",
        description="Client ID для MQTT",
    )
    topics: list[str] = Field(
        default_factory=lambda: ["gd/#"],
        description="Топики для подписки (поддерживаются wildcards + и #)",
    )
    qos: int = Field(
        default=1,
        ge=0,
        le=2,
        description="Quality of Service (0, 1, 2)",
    )
    enabled: bool = Field(
        default=False,
        description="Включить MQTT-подписку",
    )


class MqttHandler:
    """Обработчик MQTT-сообщений.

    Подписывается на топики, парсит JSON payload,
    маршрутизирует через ActionHandlerRegistry.
    """

    def __init__(self, settings: MqttSettings) -> None:
        self._settings = settings
        self._running = False
        self._task: asyncio.Task | None = None

    async def start(self) -> None:
        """Запускает фоновую подписку на MQTT-топики."""
        if not self._settings.enabled:
            logger.info("MQTT отключён (enabled=False)")
            return

        self._running = True
        self._task = asyncio.create_task(self._listen())
        logger.info(
            "MQTT handler started: %s:%d, topics=%s",
            self._settings.broker_host,
            self._settings.broker_port,
            self._settings.topics,
        )

    async def stop(self) -> None:
        """Останавливает MQTT-подписку."""
        self._running = False
        if self._task and not self._task.done():
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("MQTT handler stopped")

    async def _listen(self) -> None:
        """Основной цикл подписки."""
        try:
            import aiomqtt
        except ImportError:
            logger.warning("aiomqtt не установлен — MQTT отключён")
            return

        while self._running:
            try:
                async with aiomqtt.Client(
                    hostname=self._settings.broker_host,
                    port=self._settings.broker_port,
                    username=self._settings.username or None,
                    password=self._settings.password or None,
                    identifier=self._settings.client_id,
                ) as client:
                    for topic in self._settings.topics:
                        await client.subscribe(topic, qos=self._settings.qos)

                    async for message in client.messages:
                        await self._handle_message(
                            topic=str(message.topic),
                            payload=message.payload,
                        )

            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.error("MQTT connection error: %s. Reconnecting in 5s...", exc)
                await asyncio.sleep(5)

    async def _handle_message(self, topic: str, payload: bytes | bytearray) -> None:
        """Обрабатывает MQTT-сообщение."""
        import orjson

        try:
            data = orjson.loads(payload)
        except Exception:
            data = {"raw": payload.decode("utf-8", errors="replace")}

        action = data.pop("action", None)
        if not action:
            action = self._topic_to_action(topic)

        logger.debug("MQTT message: topic=%s, action=%s", topic, action)

        try:
            from app.dsl.commands.registry import action_handler_registry
            from app.schemas.invocation import ActionCommandSchema

            command = ActionCommandSchema(
                action=action,
                payload=data,
                meta={"source": "mqtt", "topic": topic},
            )
            await action_handler_registry.dispatch(command)
        except KeyError:
            logger.warning("MQTT: action '%s' not registered", action)
        except Exception as exc:
            logger.error("MQTT dispatch error: %s", exc)

    @staticmethod
    def _topic_to_action(topic: str) -> str:
        """Конвертирует MQTT-топик в action name.

        gd/orders/create → orders.create
        gd/events/user/login → events.user_login
        """
        parts = topic.strip("/").split("/")
        if parts and parts[0] == "gd":
            parts = parts[1:]
        if len(parts) >= 2:
            domain = parts[0]
            method = "_".join(parts[1:])
            return f"{domain}.{method}"
        return ".".join(parts) if parts else "unknown"

    async def publish(self, topic: str, data: dict[str, Any]) -> None:
        """Публикует сообщение в MQTT-топик."""
        try:
            import aiomqtt
            import orjson

            async with aiomqtt.Client(
                hostname=self._settings.broker_host,
                port=self._settings.broker_port,
                username=self._settings.username or None,
                password=self._settings.password or None,
            ) as client:
                await client.publish(
                    topic,
                    payload=orjson.dumps(data),
                    qos=self._settings.qos,
                )
        except ImportError:
            logger.warning("aiomqtt не установлен — публикация невозможна")
        except Exception as exc:
            logger.error("MQTT publish error: %s", exc)


_mqtt_handler: MqttHandler | None = None


def get_mqtt_handler() -> MqttHandler:
    """Singleton MQTT handler."""
    global _mqtt_handler
    if _mqtt_handler is None:
        try:
            settings = MqttSettings()
        except Exception:
            settings = MqttSettings(
                broker_host="localhost", broker_port=1883, enabled=False
            )
        _mqtt_handler = MqttHandler(settings)
    return _mqtt_handler
