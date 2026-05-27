"""MqttSink — публикация в MQTT-брокер (Sprint 3 V16.1 P1).

Закрывает ассиметрию: MQTT-подписка живёт в
``entrypoints/mqtt/mqtt_handler.py``, исходящий канал поднимается
до полноценного Sink-а (DSL ``sink_publish`` step + SinkRegistry).

Реализован поверх :mod:`aiomqtt` (lazy-импорт). Без установленной
библиотеки ``send`` возвращает ``SinkResult(ok=False, ...)`` —
graceful как остальные Sink-ы (см. :mod:`infrastructure.sinks`).

TLS-/mTLS-контекст собирается локально (без переноса FastAPI
singleton ``MqttHandler`` в Sink-слой).
"""

from __future__ import annotations

import ssl
from dataclasses import dataclass, field
from typing import Any

from src.backend.core.interfaces.sink import Sink, SinkKind, SinkResult
from src.backend.dsl.codec.json import dumps_bytes

__all__ = ("MqttSink",)


@dataclass(slots=True)
class MqttSink(Sink):
    """Sink публикации одного сообщения в MQTT-брокер.

    Args:
        sink_id: Уникальный идентификатор.
        broker_host: Хост MQTT-брокера.
        topic: Целевой топик (поддерживает шаблоны вида ``gd/orders/created``).
        broker_port: Порт MQTT-брокера (1883 plain / 8883 TLS).
        qos: Quality of Service (``0``/``1``/``2``).
        retain: Флаг ``MQTT retain`` — брокер сохраняет последнее
            сообщение для новых подписчиков.
        client_id: Идентификатор клиента (генерируется брокером, если пусто).
        username: Имя пользователя SASL (опционально).
        password: Пароль SASL (опционально).
        tls_enabled: Включить TLS (обязательно для публичных брокеров).
        ca_cert_path: Путь к CA-сертификату (PEM); при пустом значении
            используется системный trust-store.
        client_cert_path: Путь к клиентскому сертификату (для mTLS).
        client_key_path: Путь к клиентскому ключу (для mTLS).
        timeout: Таймаут операции connect/publish, секунды.
    """

    sink_id: str
    broker_host: str
    topic: str
    broker_port: int = 1883
    qos: int = 0
    retain: bool = False
    client_id: str | None = None
    username: str | None = None
    password: str | None = None
    tls_enabled: bool = False
    ca_cert_path: str = ""
    client_cert_path: str = ""
    client_key_path: str = ""
    timeout: float = 10.0
    kind: SinkKind = field(default=SinkKind.MQTT, init=False)

    def _build_tls_context(self) -> ssl.SSLContext | None:
        """Собирает ``ssl.SSLContext`` по полям TLS.

        Returns:
            Контекст или ``None``, если TLS отключён.
        """
        if not self.tls_enabled:
            return None
        ctx = ssl.create_default_context(cafile=self.ca_cert_path or None)
        ctx.check_hostname = True
        ctx.verify_mode = ssl.CERT_REQUIRED
        if self.client_cert_path and self.client_key_path:
            ctx.load_cert_chain(
                certfile=self.client_cert_path, keyfile=self.client_key_path
            )
        return ctx

    async def send(self, payload: Any) -> SinkResult:
        """Публикует ``payload`` в ``topic`` MQTT-брокера.

        ``payload`` сериализуется через :func:`dumps_bytes` (orjson)
        если это не ``bytes``/``str``.
        """
        try:
            import aiomqtt
        except ImportError:
            return SinkResult(ok=False, details={"error": "aiomqtt not installed"})

        if isinstance(payload, (bytes, bytearray)):
            body: bytes | str = bytes(payload)
        elif isinstance(payload, str):
            body = payload
        else:
            body = dumps_bytes(payload)

        try:
            async with aiomqtt.Client(
                hostname=self.broker_host,
                port=self.broker_port,
                username=self.username or None,
                password=self.password or None,
                identifier=self.client_id,
                tls_context=self._build_tls_context(),
                timeout=self.timeout,
            ) as client:
                await client.publish(
                    self.topic, payload=body, qos=self.qos, retain=self.retain
                )
        except Exception as exc:  # noqa: BLE001
            return SinkResult(
                ok=False, details={"error": str(exc) or exc.__class__.__name__}
            )

        return SinkResult(
            ok=True,
            details={
                "topic": self.topic,
                "qos": self.qos,
                "retain": self.retain,
                "tls": self.tls_enabled,
            },
        )

    async def health(self) -> bool:
        """Health: connect к брокеру без публикации (CONNECT/DISCONNECT)."""
        try:
            import aiomqtt
        except ImportError:
            return False
        try:
            async with aiomqtt.Client(
                hostname=self.broker_host,
                port=self.broker_port,
                username=self.username or None,
                password=self.password or None,
                identifier=self.client_id,
                tls_context=self._build_tls_context(),
                timeout=self.timeout,
            ):
                return True
        except Exception as _:  # noqa: BLE001
            return False
