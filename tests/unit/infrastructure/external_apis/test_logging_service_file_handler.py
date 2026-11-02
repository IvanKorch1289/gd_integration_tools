"""Unit tests: файловый обработчик логов не должен ронять приложение.

Регрессия (стенд 2026-10-29): контейнер ``gd-app-light`` отдавал 500 на
**все** HTTP-эндпоинты из-за ``PermissionError: [Errno 13] Permission
denied: '/app/.run/logs/dev_light.log'``. Bind-mount ``../../.run``
принадлежал uid=1000, процесс в контейнере работал как uid=10001
(``appuser``), а ``LoggerManager._create_file_handler()`` открывал файл
без обработки ``OSError`` → исключение поднималось на этапе инициализации
логирования → middleware-стек не собирался → 500 на каждый запрос.

Контракт: недоступный файловый лог → предупреждение + ``NullHandler``;
консольное/структурированное логирование продолжает работать.
"""

from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from src.backend.core.config.services.logging import LogStorageSettings
from src.backend.infrastructure.external_apis import logging_service
from src.backend.infrastructure.external_apis.logging_service import LoggerManager

__all__ = ("TestCreateFileHandler",)


def _log_config(log_dir: str, file_name: str = "app.log") -> LogStorageSettings:
    """Собрать минимальный ``LogStorageSettings`` для временного каталога."""
    return LogStorageSettings(
        host="127.0.0.1",
        port=514,
        udp_port=12201,
        use_tls=False,
        level="INFO",
        name_log_file=file_name,
        dir_log_name=log_dir,
        required_fields=["environment", "hostname", "user_id", "action"],
        log_requests=False,
        max_body_log_size=1024,
        conf_loggers=[{"name": "application", "facility": "application"}],
    )


def _make_manager(log_dir: str) -> LoggerManager:
    """Создать ``LoggerManager`` без Graylog (graylog.enabled=False)."""
    graylog = MagicMock()
    graylog.enabled = False
    return LoggerManager(
        log_config=_log_config(log_dir),
        environment="test",
        hostname="test-host",
        handler=graylog,
        debug=False,
    )


@pytest.fixture(autouse=True)
def _force_development(monkeypatch: pytest.MonkeyPatch) -> None:
    """Файловый handler создаётся только в окружении ``development``."""
    monkeypatch.setattr(
        logging_service.settings.app, "environment", "development", raising=False
    )


class TestCreateFileHandler:
    """``_create_file_handler`` — устойчивость к недоступному лог-файлу."""

    @pytest.mark.unit
    def test_unwritable_log_file_does_not_raise(self, tmp_path: Path) -> None:
        """Недоступный на запись лог-файл → NullHandler, без исключения."""
        log_dir = tmp_path / "logs"
        log_dir.mkdir()
        log_file = log_dir / "app.log"
        log_file.write_text("seed\n", encoding="utf-8")
        log_file.chmod(0o444)
        if os.geteuid() == 0:
            pytest.skip("root обходит права на файлы — сценарий не воспроизводится")

        manager = _make_manager(str(log_dir))
        try:
            handlers = manager.handlers
            assert any(isinstance(h, logging.NullHandler) for h in handlers), (
                "ожидался logging.NullHandler вместо файлового обработчика"
            )
            # Запись в логгер не должна падать.
            logging.getLogger("application").info("smoke: запись после отказа")
        finally:
            manager.shutdown()

    @pytest.mark.unit
    def test_permission_error_falls_back_to_null_handler(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """``PermissionError`` при открытии файла → NullHandler (детерминированно)."""

        def _boom(*args: Any, **kwargs: Any) -> Any:
            raise PermissionError(13, "Permission denied")

        monkeypatch.setattr(logging_service, "TimedRotatingFileHandler", _boom)

        manager = _make_manager(str(tmp_path))
        try:
            assert any(isinstance(h, logging.NullHandler) for h in manager.handlers)
        finally:
            manager.shutdown()

    @pytest.mark.unit
    def test_writable_log_dir_creates_file_handler(self, tmp_path: Path) -> None:
        """Регрессия-guard: при доступном каталоге остаётся файловый handler."""
        log_dir = tmp_path / "logs"
        manager = _make_manager(str(log_dir))
        try:
            assert not any(isinstance(h, logging.NullHandler) for h in manager.handlers)
            assert (log_dir / "app.log").exists()
        finally:
            manager.shutdown()
