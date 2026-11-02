"""Unit tests: structlog-бэкенд не должен падать на недоступном лог-файле.

Регрессия (стенд 2026-10-29): bind-mount ``.run`` принадлежал uid=1000,
процесс работал как uid=10001 → ``TimedRotatingFileHandler`` падал с
``PermissionError`` и весь logging-стек не конфигурировался (приложение
продолжало работу «на lazy defaults» — без файловых и консольных логов).
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

import pytest

from src.backend.infrastructure.logging.structlog_backend import StructlogGraylogBackend

__all__ = ("TestStructlogFileHandler",)


class TestStructlogFileHandler:
    """``StructlogGraylogBackend.configure`` — устойчивость к OSError."""

    @pytest.mark.unit
    def test_unwritable_log_file_does_not_raise(self, tmp_path: Path) -> None:
        """Недоступный на запись лог-файл → конфигурация не падает."""
        log_dir = tmp_path / "logs"
        log_dir.mkdir()
        log_file = log_dir / "app.log"
        log_file.write_text("seed\n", encoding="utf-8")
        log_file.chmod(0o444)
        if os.geteuid() == 0:
            pytest.skip("root обходит права на файлы — сценарий не воспроизводится")

        backend = StructlogGraylogBackend()
        backend.configure(
            host="",
            port=None,
            level="INFO",
            environment="test",
            log_file="app.log",
            log_dir=str(log_dir),
            debug=True,
        )
        root_handlers = logging.getLogger().handlers
        assert not any(
            isinstance(h, logging.handlers.TimedRotatingFileHandler)
            for h in root_handlers
        )
        assert any(isinstance(h, logging.StreamHandler) for h in root_handlers)

    @pytest.mark.unit
    def test_permission_error_is_swallowed(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """``PermissionError`` при создании handler'а → конфигурация не падает."""
        import logging.handlers

        def _boom(*args: Any, **kwargs: Any) -> Any:
            raise PermissionError(13, "Permission denied")

        monkeypatch.setattr(logging.handlers, "TimedRotatingFileHandler", _boom)

        backend = StructlogGraylogBackend()
        backend.configure(
            host="",
            port=None,
            level="INFO",
            environment="test",
            log_file="app.log",
            log_dir=str(tmp_path),
        )
        assert logging.getLogger().handlers is not None

    @pytest.mark.unit
    def test_writable_log_dir_creates_file_handler(self, tmp_path: Path) -> None:
        """Регрессия-guard: при доступном каталоге файловый handler создаётся."""
        backend = StructlogGraylogBackend()
        backend.configure(
            host="",
            port=None,
            level="INFO",
            environment="test",
            log_file="app.log",
            log_dir=str(tmp_path / "logs"),
        )
        assert (tmp_path / "logs" / "app.log").exists()
