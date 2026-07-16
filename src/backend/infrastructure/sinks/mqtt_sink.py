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
import time
from dataclasses import dataclass, field
from typing import Any

from src.backend.core.interfaces.sink import Sink, SinkKind, SinkResult
from src.backend.core.resilience.connector_breaker import with_breaker
from src.backend.core.resilience.connector_retry import with_retry
from src.backend.core.security.connector_auth import require_capability
from src.backend.infrastructure.clients.base_connector import HealthResult
from src.backend.infrastructure.security.connector_rate_limiter import (
    get_connector_rate_limiter,
)
from src.backend.dsl.codec.json import dumps_bytes

__all__ = ("MqttSink",)


def _default_mqtt_port() -> int:
    """Returns default MQTT port from MqttSettings."""
    from src.backend.core.config.services.mqtt import mqtt_settings

    return mqtt_settings.broker_port


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
    broker_port: int = field(default_factory=_default_mqtt_port)
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

    @with_breaker("mqtt_sink")
    @with_retry(max_attempts=3)
    @require_capability("mqtt.write", action="write")
    async def send(self, payload: Any) -> SinkResult:
        """Публикует ``payload`` в ``topic`` MQTT-брокера.

        ``payload`` сериализуется через :func:`dumps_bytes` (orjson)
        если это не ``bytes``/``str``.
        """
        # S1: per-connector rate limit (по умолчанию 100/s, 200/s для MQTT).
        limiter = get_connector_rate_limiter()
        limiter.register(f"{self.sink_id}_mqtt", "200/s", 200)
        await limiter.check(f"{self.sink_id}_mqtt")

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
        except Exception as exc:
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

    async def health(self, mode: str = "fast") -> HealthResult:
        """Health: connect к брокеру без публикации (CONNECT/DISCONNECT)."""
        try:
            import aiomqtt
        except ImportError:
            return HealthResult.failed(error="aiomqtt not installed", mode=mode)
        start = time.perf_counter()
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
                pass
        except Exception as exc:
            latency_ms = (time.perf_counter() - start) * 1000.0
            return HealthResult.failed(
                error=f"{type(exc).__name__}: {exc}", mode=mode, latency_ms=latency_ms
            )
        latency_ms = (time.perf_counter() - start) * 1000.0
        return HealthResult.ok(latency_ms=latency_ms, mode=mode)
