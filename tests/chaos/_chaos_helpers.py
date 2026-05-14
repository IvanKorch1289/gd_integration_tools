"""Внутренние хелперы chaos-тестов: общие smoke-операции и assertions.

Цель: убрать дублирование между 11 файлами test_*_chain.py. Каждый
смоук-вызов делает короткий ``ping``/``connect`` к proxy через сырой
сокет (без зависимостей от тяжёлых клиентов backend'а).

Все функции толерантны к отсутствию toxiproxy — возвращают bool вместо
raise, чтобы тест мог использовать стандартный ``assert``.
"""

from __future__ import annotations

import socket
import time

__all__ = (
    "assert_connection_fails",
    "measure_latency_ms",
    "smoke_open_socket",
)


def smoke_open_socket(host: str, port: int, *, timeout: float = 2.0) -> bool:
    """Возвращает True если TCP-handshake к target прошёл за timeout."""
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def measure_latency_ms(host: str, port: int, *, timeout: float = 5.0) -> float:
    """Замеряет latency TCP-handshake (без передачи данных)."""
    start = time.monotonic()
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return (time.monotonic() - start) * 1000.0
    except OSError:
        return -1.0


def assert_connection_fails(host: str, port: int, *, timeout: float = 1.0) -> bool:
    """True если соединение НЕ устанавливается (для disconnect-сценариев)."""
    return not smoke_open_socket(host, port, timeout=timeout)
