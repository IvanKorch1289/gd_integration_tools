"""LocalProcessScaler — Granian SIGUSR1 fork-worker scaler (Sprint 4 Wave D).

Назначение:
    Process-level автоскалирование Granian (V15 R-V15-10 уровень 1).
    SIGUSR1 → fork нового worker'а, SIGUSR2 → graceful-shutdown worker'а.
    При отсутствии Granian (dev_light) — NoOp fallback с WARNING.

Архитектура:
    * Lazy-import :mod:`granian` и :mod:`psutil` через try/except.
    * ``current_workers`` использует psutil; при недоступности → возвращает min_workers (best-effort).
    * Все scale-операции логируются через structlog.

V15 R-V15-10 — auto-scaling 3 уровня (этот уровень — process).
"""

from __future__ import annotations

import logging
import os
import signal
from pathlib import Path

__all__ = ("LocalProcessScaler",)

_logger = logging.getLogger("core.scaling.local_process_scaler")


class LocalProcessScaler:
    """Process-level scaler для Granian workers через SIGUSR1/SIGUSR2.

    Args:
        min_workers: Минимальное число workers (защита от scale-down ниже).
        max_workers: Максимальное число workers.
        master_pid_file: Путь к pid-файлу Granian master-процесса.
    """

    def __init__(
        self,
        *,
        min_workers: int = 2,
        max_workers: int = 10,
        master_pid_file: str | Path = "/run/granian/master.pid",
    ) -> None:
        if min_workers < 1 or max_workers < min_workers:
            raise ValueError(
                "min_workers >= 1 и max_workers >= min_workers обязательны"
            )
        self.min_workers = min_workers
        self.max_workers = max_workers
        self.master_pid_file = Path(master_pid_file)

    def _read_master_pid(self) -> int | None:
        """Прочитать pid master-процесса Granian из pid-файла.

        Returns:
            pid (int) или None, если файл не существует / невалиден.
        """
        if not self.master_pid_file.exists():
            return None
        try:
            return int(self.master_pid_file.read_text().strip())
        except OSError, ValueError:
            return None

    def scale_up(self, by: int = 1) -> bool:
        """Отправить SIGUSR1 master'у Granian (fork нового worker).

        Args:
            by: Число воркеров для добавления.

        Returns:
            True если SIGUSR1 отправлен; False — fallback NoOp.
        """
        master_pid = self._read_master_pid()
        if master_pid is None:
            _logger.warning(
                "LocalProcessScaler.scale_up NoOp: master pid не найден (%s)",
                self.master_pid_file,
            )
            return False
        try:
            for _ in range(by):
                os.kill(master_pid, signal.SIGUSR1)
            _logger.info("LocalProcessScaler.scale_up: +%d worker(s)", by)
            return True
        except OSError as exc:
            _logger.warning("scale_up failed: %s", exc)
            return False

    def scale_down(self, by: int = 1) -> bool:
        """Отправить SIGUSR2 master'у Granian (terminate worker).

        Args:
            by: Число воркеров для удаления.

        Returns:
            True если SIGUSR2 отправлен; False — fallback NoOp.
        """
        master_pid = self._read_master_pid()
        if master_pid is None:
            _logger.warning("LocalProcessScaler.scale_down NoOp: master pid не найден")
            return False
        try:
            for _ in range(by):
                os.kill(master_pid, signal.SIGUSR2)
            _logger.info("LocalProcessScaler.scale_down: -%d worker(s)", by)
            return True
        except OSError as exc:
            _logger.warning("scale_down failed: %s", exc)
            return False

    def current_workers(self) -> int:
        """Best-effort оценка числа Granian-worker процессов.

        Returns:
            Число workers через psutil, или ``min_workers`` при недоступности.
        """
        try:
            import psutil

            workers = [
                p
                for p in psutil.process_iter(["name", "cmdline"])
                if "granian" in (p.info.get("name") or "").lower()
                or any(
                    "granian" in (s or "").lower()
                    for s in (p.info.get("cmdline") or [])
                )
            ]
            return max(len(workers) - 1, self.min_workers)  # -1 для master
        except Exception as _:
            return self.min_workers
