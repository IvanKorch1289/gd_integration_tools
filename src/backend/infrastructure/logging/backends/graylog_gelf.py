"""``GraylogGelfLogSink`` — отправка логов в Graylog по протоколу GELF.

Поддерживаются два транспорта:

* ``udp`` — стандартный GELF UDP (быстрый, без подтверждений);
* ``tcp`` — GELF TCP (с делимитером ``\\x00``, надёжнее, но медленнее).

Сериализация GELF-payload — ручная (структура GELF 1.1), это позволяет
не зависеть жёстко от ``pygelf`` / ``graypy``: если опциональный пакет
не установлен, sink продолжает работать через сырой socket.

Sprint 0 hotfix V16 (unit #9): persistent connection + async queue +
circuit breaker.

Persistent connection
---------------------
Для **TCP**: одно соединение на инстанс sink-а. Сокет создаётся при
первой отправке и переиспользуется для последующих логов; при
ошибке I/O — закрывается и пересоздаётся при следующей попытке.
Для **UDP**: один long-lived datagram-socket переиспользуется (UDP
connectionless, но переоткрытие сокета на каждый лог — лишний
syscall, поэтому держим один).

Async queue
-----------
Между ``write()`` (вызывается из structlog) и фактической отправкой
в Graylog стоит :class:`asyncio.Queue` с background drain-task'ом.
Это защищает event loop от блокировки на медленном Graylog: запись
ставится в очередь за O(1), drain-worker сливает её в сокет
последовательно. При переполнении очереди (Graylog недоступен >
``queue_maxsize`` логов) — новые записи отбрасываются с инкрементом
счётчика ``dropped`` (не блокируем логгер).

Circuit breaker
---------------
Drain-worker оборачивает send в :class:`Breaker` (purgatory):

* при N подряд OSError breaker → ``open``, ``is_healthy = False``;
* router (``SinkRouter``) видит ``is_healthy = False`` и пропускает
  sink, переключаясь на fallback (обычно ``DiskRotatingLogSink``);
* через ``recovery_timeout`` breaker → ``half_open``, при успешном
  send → ``closed`` + ``is_healthy = True``.

Reconnect
---------
При ошибке отправки (broken pipe / connection reset) сокет
закрывается; следующая итерация drain-worker'а пересоздаст соединение.
Tenacity не нужен для самого reconnect — purgatory + drain-loop
обеспечивают backoff естественным образом (recovery_timeout breaker'а).
"""

from __future__ import annotations

import asyncio
import logging
import socket
import time
import zlib
from typing import Any, Final, Literal

import orjson

from src.backend.core.interfaces.log_sink import LogSink
from src.backend.infrastructure.resilience.breaker import (
    Breaker,
    BreakerSpec,
    CircuitOpen,
    breaker_registry,
)

__all__ = ("GraylogGelfLogSink", "GelfProtocol")


GelfProtocol = Literal["udp", "tcp"]

_GELF_VERSION: Final[str] = "1.1"
_TCP_DELIMITER: Final[bytes] = b"\x00"
_DEFAULT_QUEUE_MAXSIZE: Final[int] = 10_000
_INTERNAL_LOG = logging.getLogger("logging.graylog_gelf")

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
    """GELF-sink для Graylog с persistent connection, queue и circuit-breaker.

    Аргументы:
        host: hostname/IP Graylog inputа.
        port: порт GELF input.
        protocol: ``"udp"`` или ``"tcp"``.
        name: имя sink-а для метрик.
        compress: сжимать UDP payload через zlib (полезно для длинных событий).
        breaker_spec: параметры circuit-breaker (порог отказов / TTL).
        connect_timeout: таймаут TCP-подключения в секундах.
        queue_maxsize: размер async-очереди между ``write()`` и drain-worker'ом.
            При переполнении новые записи отбрасываются (см. ``dropped``).

    Если ``protocol="udp"`` и payload длиннее 8192 байт — отправляется в
    сжатом виде (zlib). Chunked GELF мы намеренно не реализуем —
    проект использует TCP для крупных событий.

    Жизненный цикл:
        * первый ``write()`` лениво стартует background drain-task;
        * drain-task в цикле читает очередь и отправляет через breaker.guard();
        * ``close()`` дренирует очередь, отменяет worker, закрывает сокеты.
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
        queue_maxsize: int = _DEFAULT_QUEUE_MAXSIZE,
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

        # queue + drain-worker (lazy-init)
        self._queue: asyncio.Queue[bytes] = asyncio.Queue(maxsize=max(1, queue_maxsize))
        self._worker_task: asyncio.Task[None] | None = None
        self._closed = False
        self._dropped: int = 0

    # ------------------------------------------------------------------ public API
    @property
    def dropped(self) -> int:
        """Счётчик записей, отброшенных при переполнении очереди."""
        return self._dropped

    @property
    def queue_size(self) -> int:
        """Текущий размер очереди (для метрик)."""
        return self._queue.qsize()

    async def write(self, record: dict[str, Any]) -> None:
        """Сериализовать ``record`` в GELF и поставить в очередь на отправку.

        Не блокирует event loop: сериализация локальная, queue.put_nowait
        выполняется за O(1). Если breaker уже ``open`` — запись
        отбрасывается без помещения в очередь (sink помечен unhealthy,
        router переключается на fallback).

        При переполнении очереди (Graylog недоступен или медленный)
        запись отбрасывается с инкрементом ``dropped``; первый drop
        логируется во внутренний логгер на уровне WARNING.
        """
        if self._closed:
            return

        if self._breaker.is_open:
            self.is_healthy = False
            return

        try:
            payload = self._serialize(record)
        except (TypeError, ValueError):
            # fallback: всё неизвестное → str
            payload = self._serialize({k: _coerce(v) for k, v in record.items()})

        try:
            self._queue.put_nowait(payload)
        except asyncio.QueueFull:
            self._dropped += 1
            if self._dropped == 1 or self._dropped % 1000 == 0:
                _INTERNAL_LOG.warning(
                    "graylog queue full, dropped=%d (host=%s)",
                    self._dropped,
                    self._host,
                )
            return

        self._ensure_worker()

    async def flush(self) -> None:
        """Дренировать очередь до пустого состояния.

        Используется в ``aclose`` router'а перед закрытием sink-а — чтобы
        накопленные логи стартапа/штатной остановки гарантированно
        ушли в Graylog (либо сбросились в DLQ при ``open`` breaker'е).
        """
        # ждём пока worker не вычитает всё из очереди
        # с защитой от вечного ожидания если breaker open и записи дропаются
        deadline = asyncio.get_running_loop().time() + 2.0
        while not self._queue.empty():
            if asyncio.get_running_loop().time() > deadline:
                break
            await asyncio.sleep(0.01)

    async def close(self) -> None:
        """Корректно завершить sink: остановить worker, закрыть сокеты."""
        self._closed = True
        if self._worker_task is not None and not self._worker_task.done():
            self._worker_task.cancel()
            try:
                await self._worker_task
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass
        await asyncio.to_thread(self._close_sockets)

    # ------------------------------------------------------------------ private: worker
    def _ensure_worker(self) -> None:
        """Запустить drain-worker, если ещё не запущен."""
        if self._worker_task is not None and not self._worker_task.done():
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            return
        self._worker_task = loop.create_task(
            self._drain_loop(), name=f"graylog-drain[{self.name}]"
        )

    async def _drain_loop(self) -> None:
        """Фоновый цикл: читать очередь, отправлять через breaker.guard()."""
        while not self._closed:
            try:
                payload = await self._queue.get()
            except asyncio.CancelledError:
                return

            try:
                async with self._breaker.guard():
                    await asyncio.to_thread(self._send, payload)
                    self.is_healthy = True
            except CircuitOpen:
                # breaker открыт — sink unhealthy; payload теряется
                # (router переключился на disk-fallback задолго до этого)
                self.is_healthy = False
            except OSError:
                # purgatory увеличил failure-counter; sink остаётся "живым",
                # но текущая запись потеряна; reconnect — на следующей итерации
                self.is_healthy = False
            except Exception:  # noqa: BLE001
                # любой неожиданный сбой не должен ронять worker
                self.is_healthy = False
                _INTERNAL_LOG.exception("graylog drain unexpected error")
            finally:
                self._queue.task_done()

    # ------------------------------------------------------------------ private: serialize/send
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
        """UDP-отправка через persistent datagram-socket."""
        if self._compress and len(payload) > 1024:
            payload = zlib.compress(payload)
        if self._udp_socket is None:
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            self._udp_socket = sock
        try:
            self._udp_socket.sendto(payload, (self._host, self._port))
        except OSError:
            # переоткрыть сокет на следующей попытке
            try:
                self._udp_socket.close()
            except OSError:
                pass
            self._udp_socket = None
            raise

    def _send_tcp(self, payload: bytes) -> None:
        """TCP-отправка через persistent connection с auto-reconnect.

        Включает SO_KEEPALIVE для обнаружения "тихих" разрывов соединения
        (Graylog за load balancer'ом, NAT-таймауты).
        """
        if self._tcp_socket is None:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.settimeout(self._connect_timeout)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
            # TCP keepalive: проверяем idle-соединение каждые ~30s
            if hasattr(socket, "TCP_KEEPIDLE"):
                sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPIDLE, 30)
            if hasattr(socket, "TCP_KEEPINTVL"):
                sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPINTVL, 10)
            if hasattr(socket, "TCP_KEEPCNT"):
                sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPCNT, 3)
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
        """Закрыть UDP/TCP сокеты, если были созданы."""
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
