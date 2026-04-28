"""Structlog бэкенд с поддержкой Graylog (GELF).

Структурированное логирование через structlog с автоматической
отправкой в Graylog. Поддерживает JSON-формат, привязку
контекста, обогащение метаданными.

Переключение на этот бэкенд:
    from src.infrastructure.logging.structlog_backend import StructlogGraylogBackend
    backend = StructlogGraylogBackend()
    backend.configure(host="graylog.example.com", port=12201, ...)
    logger = backend.get_logger("application")
    logger.info("Order created", order_id=123)
"""

import logging
import logging.handlers
import sys
from typing import Any

from src.infrastructure.logging.base import BaseLoggerBackend, LoggerProtocol

__all__ = ("StructlogGraylogBackend",)


class StructlogLogger(LoggerProtocol):
    """Обёртка structlog.BoundLogger под LoggerProtocol."""

    def __init__(self, inner: Any) -> None:
        self._inner = inner

    def debug(self, msg: str, **kwargs: Any) -> None:
        self._inner.debug(msg, **kwargs)

    def info(self, msg: str, **kwargs: Any) -> None:
        self._inner.info(msg, **kwargs)

    def warning(self, msg: str, **kwargs: Any) -> None:
        self._inner.warning(msg, **kwargs)

    def error(self, msg: str, **kwargs: Any) -> None:
        self._inner.error(msg, **kwargs)

    def exception(self, msg: str, **kwargs: Any) -> None:
        self._inner.exception(msg, **kwargs)

    def bind(self, **kwargs: Any) -> "StructlogLogger":
        return StructlogLogger(self._inner.bind(**kwargs))


class StructlogGraylogBackend(BaseLoggerBackend):
    """Structlog + Graylog (GELF) бэкенд.

    Настраивает structlog pipeline:
    1. Привязка контекста (environment, hostname)
    2. Добавление timestamp, log_level, caller_info
    3. JSON-рендеринг
    4. Вывод в: Graylog (GELF UDP/TLS) + console + файл
    """

    def __init__(self) -> None:
        self._configured = False
        self._loggers: dict[str, StructlogLogger] = {}

    def configure(
        self,
        *,
        host: str = "",
        port: int = 12201,
        use_tls: bool = False,
        ca_bundle: str | None = None,
        level: str = "INFO",
        environment: str = "production",
        log_file: str | None = None,
        log_dir: str | None = None,
        debug: bool = False,
        logger_names: list[str] | None = None,
        **_extra: Any,
    ) -> None:
        """Настраивает structlog + stdlib logging бэкенды."""
        try:
            import structlog
        except ImportError as exc:
            raise ImportError(
                "structlog не установлен. Добавьте: pip install structlog"
            ) from exc

        from socket import gethostname

        hostname = gethostname()

        # stdlib logging handlers
        handlers: list[logging.Handler] = []

        # Graylog GELF handler
        if host and port:
            try:
                import graypy

                handler_cls = (
                    graypy.GELFTLSHandler if use_tls else graypy.GELFUDPHandler
                )
                gelf_kwargs: dict[str, Any] = {}
                if use_tls and ca_bundle:
                    gelf_kwargs["ca_certs"] = ca_bundle
                gelf_handler = handler_cls(host, port, **gelf_kwargs)
                handlers.append(gelf_handler)
            except ImportError:
                pass

        # Console handler
        if debug:
            console = logging.StreamHandler(sys.stdout)
            console.setLevel(logging.DEBUG)
            handlers.append(console)

        # File handler
        if log_file and log_dir:
            from pathlib import Path

            log_path = Path(log_dir)
            log_path.mkdir(parents=True, exist_ok=True)
            file_handler = logging.handlers.TimedRotatingFileHandler(
                filename=str(log_path / log_file),
                when="midnight",
                interval=1,
                backupCount=7,
                encoding="utf-8",
            )
            handlers.append(file_handler)

        # Configure stdlib root logger
        log_level = getattr(logging, level.upper(), logging.INFO)
        logging.basicConfig(
            format="%(message)s", level=log_level, handlers=handlers, force=True
        )

        # Configure per-name loggers
        names = logger_names or []
        for name in names:
            stdlib_logger = logging.getLogger(name)
            stdlib_logger.setLevel(log_level)
            stdlib_logger.propagate = False
            for h in stdlib_logger.handlers[:]:
                stdlib_logger.removeHandler(h)
            for h in handlers:
                stdlib_logger.addHandler(h)

        # Correlation context injector
        def _inject_correlation(
            logger: Any, method_name: str, event_dict: dict
        ) -> dict:
            """Автоматически добавляет correlation_id/request_id/tenant_id в каждый лог."""
            try:
                from src.infrastructure.observability.correlation import (
                    get_correlation_id,
                    get_request_id,
                    get_tenant_id,
                )

                if cid := get_correlation_id():
                    event_dict.setdefault("correlation_id", cid)
                if rid := get_request_id():
                    event_dict.setdefault("request_id", rid)
                if tid := get_tenant_id():
                    event_dict.setdefault("tenant_id", tid)
            except (ImportError, AttributeError):
                pass
            return event_dict

        # Structlog pipeline
        shared_processors: list[Any] = [
            structlog.contextvars.merge_contextvars,
            _inject_correlation,
            structlog.stdlib.add_logger_name,
            structlog.stdlib.add_log_level,
            structlog.stdlib.ExtraAdder(),
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.UnicodeDecoder(),
        ]

        if debug:
            renderer = structlog.dev.ConsoleRenderer()
        else:
            renderer = structlog.processors.JSONRenderer()

        structlog.configure(
            processors=[
                *shared_processors,
                structlog.stdlib.ProcessorFormatter.wrap_for_formatter,
            ],
            logger_factory=structlog.stdlib.LoggerFactory(),
            wrapper_class=structlog.stdlib.BoundLogger,
            cache_logger_on_first_use=True,
            context_class=dict,
        )

        # Bind default context
        structlog.contextvars.clear_contextvars()
        structlog.contextvars.bind_contextvars(
            environment=environment, hostname=hostname
        )

        # Formatter for stdlib handlers
        formatter = structlog.stdlib.ProcessorFormatter(
            processors=[
                structlog.stdlib.ProcessorFormatter.remove_processors_meta,
                renderer,
            ]
        )
        for h in handlers:
            h.setFormatter(formatter)

        self._configured = True

    def get_logger(self, name: str) -> StructlogLogger:
        """Возвращает structlog-логгер с привязанным именем."""
        if name in self._loggers:
            return self._loggers[name]

        try:
            import structlog

            inner = structlog.get_logger(name)
        except ImportError:
            import logging as _logging

            inner = _logging.getLogger(name)

        logger = StructlogLogger(inner)
        self._loggers[name] = logger
        return logger

    def shutdown(self) -> None:
        """Завершает работу — flush всех handler'ов."""
        for handler in logging.root.handlers[:]:
            handler.flush()
            handler.close()
        self._loggers.clear()
        self._configured = False
