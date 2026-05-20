"""Внутренние хелперы chaos-тестов: общие smoke-операции и assertions.

Цель: убрать дублирование между 11 файлами test_*_chain.py. Каждый
смоук-вызов делает короткий ``ping``/``connect`` к proxy через сырой
сокет (без зависимостей от тяжёлых клиентов backend'а).

Все функции толерантны к отсутствию toxiproxy — возвращают bool вместо
raise, чтобы тест мог использовать стандартный ``assert``.
"""

from __future__ import annotations

import importlib
import socket
import time

__all__ = (
    "SCENARIOS",
    "assert_chain_module_loadable",
    "assert_connection_fails",
    "measure_latency_ms",
    "smoke_open_socket",
)

# Унифицированные toxiproxy-сценарии для всех chain-chaos-тестов
# (S11 carryover: добавлены, чтобы убрать collection-ImportError в 11
# файлах ``tests/chaos/test_*_chain_chaos.py``).
SCENARIOS: tuple[str, ...] = ("slow", "error", "disconnect")


def assert_chain_module_loadable(dotted_path: str) -> None:
    """Проверяет, что resilience-chain модуль действительно импортируется.

    Используется как smoke-assertion в chaos-тестах: запускается до toxic-
    инжекта чтобы зафиксировать, что сам chain жив. В случае отсутствия
    модуля бросает ``AssertionError`` — pytest помечает тест Failed,
    а не Error (collection error).
    """
    try:
        importlib.import_module(dotted_path)
    except ImportError as exc:  # noqa: BLE001
        raise AssertionError(
            f"chain module {dotted_path!r} not loadable: {exc}"
        ) from exc


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
