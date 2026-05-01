"""``GraylogGelfLogSink`` — отправка логов в Graylog по протоколу GELF.

Поддерживаются два транспорта:

* ``udp`` — стандартный GELF UDP (быстрый, без подтверждений);
* ``tcp`` — GELF TCP (с делимитером ``\\x00``, надёжнее, но медленнее).

Сериализация GELF-payload — ручная (структура GELF 1.1), это позволяет
не зависеть жёстко от ``pygelf`` / ``graypy``: если опциональный пакет
не установлен, sink продолжает работать через сырой socket.

Отказоустойчивость:

* отправка обёрнута в :class:`~src.infrastructure.resilience.breaker.Breaker`
  (purgatory): при N подряд ошибках breaker переходит в ``open``,
  ``is_healthy`` становится ``False`` и router начинает использовать
  fallback-sink (обычно :class:`DiskRotatingLogSink`);
* собственная отправка запускается через :func:`asyncio.to_thread`,
  чтобы блокирующий ``socket.sendto`` не задерживал event loop.
"""

from __future__ import annotations

import asyncio
import socket
import time
import zlib
from typing import Any, Final, Literal

import orjson

from src.core.interfaces.log_sink import LogSink
from src.infrastructure.resilience.breaker import (
    Breaker,
    BreakerSpec,
    CircuitOpen,
    breaker_registry,
)

__all__ = ("GraylogGelfLogSink", "GelfProtocol")


GelfProtocol = Literal["udp", "tcp"]

_GELF_VERSION: Final[str] = "1.1"
_TCP_DELIMITER: Final[bytes] = b"\x00"
# отображение log-level structlog → syslog severity (RFC 5424)
_LEVEL_TO_SYSLOG: Final[dict[str, int]] = {
    "critical": 2,
    "error": 3,
    "warning": 4,
    "warn": 4,
    "info": 6,
    "debug": 7,
    "notset": 7,
}


class GraylogGelfLogSink(LogSink):
    """GELF-sink для Graylog с circuit-breaker и graceful degradation.

    Аргументы:
        host: hostname/IP Graylog inputа.
        port: порт GELF input.
        protocol: ``"udp"`` или ``"tcp"``.
        name: имя sink-а для метрик.
        compress: сжимать UDP payload через zlib (полезно для длинных событий).
        breaker_spec: параметры circuit-breaker (порог отказов / TTL).
        connect_timeout: таймаут TCP-подключения в секундах.

    Если ``protocol="udp"`` и payload длиннее 8192 байт — отправляется в
    сжатом виде (zlib). Chunked GELF мы намеренно не реализуем —
    проект использует TCP для крупных событий.
    """

    def __init__(
        self,
        *,
        host: str,
        port: int,
        protocol: GelfProtocol = "udp",
        name: str = "graylog_gelf",
        compress: bool = True,
        breaker_spec: BreakerSpec | None = None,
        connect_timeout: float = 2.0,
    ) -> None:
        self.name = name
        self.is_healthy = True
        self._host = host
        self._port = port
        self._protocol: GelfProtocol = protocol
        self._compress = compress
        self._connect_timeout = connect_timeout
        self._breaker: Breaker = breaker_registry.get_or_create(
            f"log_sink:{name}", breaker_spec or BreakerSpec(), host=host
        )
        self._tcp_socket: socket.socket | None = None
        self._udp_socket: socket.socket | None = None
        # имя источника — как в pygelf, через socket.gethostname()
        self._source = socket.gethostname()

    # ------------------------------------------------------------------ public API
    async def write(self, record: dict[str, Any]) -> None:
        """Сериализовать ``record`` в GELF и отправить через guard breaker.

        Если breaker в состоянии ``open`` — попытка отправки сразу
        пропускается; ``is_healthy`` становится ``False``, чтобы router
        переключился на fallback sink.
        """
        if self._breaker.is_open:
            self.is_healthy = False
            return

        try:
            payload = self._serialize(record)
        except (TypeError, ValueError):
            # fallback: всё неизвестное → str
            payload = self._serialize({k: _coerce(v) for k, v in record.items()})

        try:
            async with self._breaker.guard():
                await asyncio.to_thread(self._send, payload)
                self.is_healthy = True
        except CircuitOpen:
            self.is_healthy = False
        except OSError:
            # покрыто failure-counter breaker'а; sink остаётся «живым»,
            # но текущая запись потеряна
            self.is_healthy = False

    async def flush(self) -> None:
        """GELF/UDP не имеет буфера; для TCP — попытка ``flush`` сокета."""
        if self._protocol == "tcp" and self._tcp_socket is not None:
            try:
                # у TCP-сокета нет flush(), но можно попытаться послать пустой ping;
                # вместо этого просто проверяем, что сокет не в ошибочном состоянии
                await asyncio.to_thread(self._tcp_socket.getpeername)
            except OSError:
                self.is_healthy = False

    async def close(self) -> None:
        """Закрыть UDP/TCP сокеты, если были созданы."""
        await asyncio.to_thread(self._close_sockets)

    # ------------------------------------------------------------------ private
    def _serialize(self, record: dict[str, Any]) -> bytes:
        """Сформировать GELF-1.1 payload из event_dict."""
        gelf: dict[str, Any] = {
            "version": _GELF_VERSION,
            "host": self._source,
            "short_message": str(record.get("event") or record.get("message") or ""),
            "timestamp": float(record.get("timestamp_unix") or time.time()),
            "level": _LEVEL_TO_SYSLOG.get(str(record.get("level", "info")).lower(), 6),
        }
        for key, value in record.items():
            if key in {"event", "message", "level", "timestamp", "timestamp_unix"}:
                continue
            # GELF additional-field: ключ должен начинаться с "_"
            gelf_key = key if key.startswith("_") else f"_{key}"
            gelf[gelf_key] = _coerce(value)

        return orjson.dumps(gelf, default=_default_serializer)

    def _send(self, payload: bytes) -> None:
        """Отправить payload в Graylog (синхронно, под :func:`to_thread`)."""
        match self._protocol:
            case "udp":
                self._send_udp(payload)
            case "tcp":
                self._send_tcp(payload)

    def _send_udp(self, payload: bytes) -> None:
        if self._compress and len(payload) > 1024:
            payload = zlib.compress(payload)
        sock = self._udp_socket or socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._udp_socket = sock
        sock.sendto(payload, (self._host, self._port))

    def _send_tcp(self, payload: bytes) -> None:
        if self._tcp_socket is None:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(self._connect_timeout)
            sock.connect((self._host, self._port))
            self._tcp_socket = sock
        try:
            self._tcp_socket.sendall(payload + _TCP_DELIMITER)
        except OSError:
            # переподключение при следующей попытке
            try:
                self._tcp_socket.close()
            except OSError:
                pass
            self._tcp_socket = None
            raise

    def _close_sockets(self) -> None:
        for attr in ("_udp_socket", "_tcp_socket"):
            sock: socket.socket | None = getattr(self, attr, None)
            if sock is not None:
                try:
                    sock.close()
                except OSError:
                    pass
                setattr(self, attr, None)


# ---------------------------------------------------------------------- helpers


def _default_serializer(value: Any) -> Any:
    """Fallback сериализатор для ``orjson.dumps``."""
    return str(value)


def _coerce(value: Any) -> Any:
    """Жёсткое приведение значения к GELF-совместимому типу."""
    if isinstance(value, (str, int, float, bool, type(None))):
        return value
    if isinstance(value, (list, tuple, set)):
        return [_coerce(v) for v in value]
    if isinstance(value, dict):
        return {str(k): _coerce(v) for k, v in value.items()}
    return str(value)
