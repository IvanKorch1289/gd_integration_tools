"""Structlog бэкенд с поддержкой Graylog (GELF).

Структурированное логирование через structlog с автоматической
отправкой в Graylog. Поддерживает JSON-формат, привязку
контекста, обогащение метаданными.

Переключение на этот бэкенд:
    from src.backend.infrastructure.logging.structlog_backend import StructlogGraylogBackend
    backend = StructlogGraylogBackend()
    backend.configure(host="graylog.example.com", port=12201, ...)
    logger = backend.get_logger("application")
    logger.info("Order created", order_id=123)
"""

import logging
import logging.handlers
import sys
from typing import Any

from src.backend.infrastructure.logging.base import BaseLoggerBackend, LoggerProtocol

__all__ = ("StructlogGraylogBackend",)


class StructlogLogger(LoggerProtocol):
    """Обёртка structlog.BoundLogger под LoggerProtocol.

    Sprint 60 W1 — compat shim: поддерживает **и** kwargs-only API structlog
    (``logger.info("msg", key=val)``), **и** stdlib-style позиционные args
    (``logger.info("msg %s", arg)``). При наличии ``*args`` — выполняется
    ``msg % args`` форматирование (как в stdlib ``logging``), результат
    передаётся в structlog как plain message.

    Также корректно обрабатывает ``exc_info=True`` (через structlog kwarg).
    """

    def __init__(self, inner: Any) -> None:
        self._inner = inner

    @property
    def name(self) -> str:
        """Sprint 60 W2 — обратная совместимость: ``logger.name`` → structlog logger name."""
        # structlog.BoundLogger хранит имя в self._inner._logger.name (stdlib обёртка)
        inner = self._inner
        if hasattr(inner, "_logger"):
            return getattr(inner._logger, "name", inner.__class__.__name__)
        if hasattr(inner, "name"):
            return inner.name
        return inner.__class__.__name__

    @staticmethod
    def _format(msg: str, args: tuple[Any, ...], kwargs: dict[str, Any]) -> tuple[str, dict[str, Any]]:
        """Compat shim: stdlib-style ``%`` formatting → structlog kwargs.

        Returns:
            (formatted_message, merged_kwargs) — готово к передаче в structlog.
        """
        if not args:
            return msg, kwargs
        try:
            formatted = msg % args
            return formatted, kwargs
        except (TypeError, ValueError):
            # msg не содержит %-placeholders ИЛИ args не подходят — отдаём как есть
            # (structlog не упадёт; при рендере JSON просто увидит str)
            return msg, {**kwargs, "args": list(args)}

    def debug(self, msg: str, *args: Any, **kwargs: Any) -> None:
        formatted, merged = self._format(msg, args, kwargs)
        self._inner.debug(formatted, **merged)

    def info(self, msg: str, *args: Any, **kwargs: Any) -> None:
        formatted, merged = self._format(msg, args, kwargs)
        self._inner.info(formatted, **merged)

    def warning(self, msg: str, *args: Any, **kwargs: Any) -> None:
        formatted, merged = self._format(msg, args, kwargs)
        self._inner.warning(formatted, **merged)

    def error(self, msg: str, *args: Any, **kwargs: Any) -> None:
        formatted, merged = self._format(msg, args, kwargs)
        self._inner.error(formatted, **merged)

    def exception(self, msg: str, *args: Any, **kwargs: Any) -> None:
        formatted, merged = self._format(msg, args, kwargs)
        # stdlib-семантика: exception() по умолчанию exc_info=True
        merged.setdefault("exc_info", True)
        self._inner.exception(formatted, **merged)

    def critical(self, msg: str, *args: Any, **kwargs: Any) -> None:
        formatted, merged = self._format(msg, args, kwargs)
        self._inner.critical(formatted, **merged)

    def log(self, level: int, msg: str, *args: Any, **kwargs: Any) -> None:
        formatted, merged = self._format(msg, args, kwargs)
        self._inner.log(level, formatted, **merged)

    def isEnabledFor(self, level: int) -> bool:  # noqa: N802
        return self._inner.isEnabledFor(level)

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
        port: int | None = None,
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
        # Use settings defaults if not provided
        from src.backend.core.config.services.logging import log_settings

        if port is None:
            port = log_settings.port
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
                from src.backend.infrastructure.observability.correlation import (
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
            except ImportError, AttributeError:
                pass
            return event_dict

        # Structlog pipeline.
        #
        # Wave 2.5 (Roadmap V10): после всех обогащающих processor'ов и
        # ДО ``wrap_for_formatter`` подключаем :func:`route_to_sinks`.
        # Sinks получают финальный обогащённый event_dict (с timestamp,
        # log_level, correlation_id, …) и сами решают, как сериализовать
        # его в свой транспорт. Если глобальный :class:`SinkRouter`
        # ещё не инициализирован, ``route_to_sinks`` работает как no-op
        # (см. :func:`is_router_configured`).
        from src.backend.infrastructure.logging.router import route_to_sinks
        from src.backend.infrastructure.observability.pii_filter import mask_pii

        shared_processors: list[Any] = [
            structlog.contextvars.merge_contextvars,
            _inject_correlation,
            structlog.stdlib.add_logger_name,
            structlog.stdlib.add_log_level,
            structlog.stdlib.ExtraAdder(),
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.UnicodeDecoder(),
            # V15 S1: PII redaction перед роутингом в backends.
            # Маскирует email/phone/passport/snils/inn/card во всём event_dict.
            mask_pii,
            route_to_sinks,
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
        """Завершает работу — flush всех handler'ов + sync-close GELF sink'ов.

        Sprint 60 W1 — fix S-L7-3 (GELF FD leak): вызывает
        :meth:`GraylogGelfLogSink.close_sync` для всех активных sink'ов,
        зарегистрированных в :class:`SinkRouter` (без event loop, sync
        path). Это гарантирует закрытие persistent UDP/TCP сокетов
        даже при вызове из ``atexit`` / signal-handler / sync-контекста,
        когда ``asyncio.to_thread`` уже не сработает.
        """
        # 1) sync-close GELF sinks (если router инициализирован)
        try:
            from src.backend.infrastructure.logging.router import (
                get_router,
                is_router_configured,
            )

            if is_router_configured():
                router = get_router()
                for sink in router._sinks:  # noqa: SLF001 — internal access
                    if hasattr(sink, "close_sync"):
                        try:
                            sink.close_sync()
                        except Exception:  # noqa: BLE001 — best-effort cleanup
                            pass
        except Exception:  # noqa: BLE001
            # router может быть ещё не инициализирован — no-op
            pass

        # 2) flush + close stdlib handlers
        for handler in logging.root.handlers[:]:
            try:
                handler.flush()
                handler.close()
            except Exception:  # noqa: BLE001
                pass

        self._loggers.clear()
        self._configured = False
