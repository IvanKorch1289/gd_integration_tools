"""Конфигурация HTTP/3-сервера.

Лёгкий dataclass без зависимости от ``aioquic`` — используется в CLI,
тестах и при инициализации сервера.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

__all__ = ("Http3ServerConfig",)


@dataclass(frozen=True, slots=True)
class Http3ServerConfig:
    """Параметры HTTP/3 + WebTransport сервера."""

    host: str
    port: int
    certfile: Path
    keyfile: Path
    max_datagram_frame_size: int = 65536
    idle_timeout: float = 60.0
    alpn_protocols: tuple[str, ...] = ("h3", "h3-29")

    def __post_init__(self) -> None:
        if not self.certfile.exists():
            raise FileNotFoundError(
                f"HTTP/3 certfile не найден: {self.certfile}. "
                "Укажите валидный PEM через APP_HTTP3_CERTFILE."
            )
        if not self.keyfile.exists():
            raise FileNotFoundError(
                f"HTTP/3 keyfile не найден: {self.keyfile}. "
                "Укажите валидный PEM через APP_HTTP3_KEYFILE."
            )
