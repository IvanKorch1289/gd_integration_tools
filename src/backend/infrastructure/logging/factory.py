# ruff: noqa: F401 — false positive (optional-import probe / re-export / availability check)
"""Фабрика логирования — единая точка получения логгеров.

Автоматически выбирает бэкенд:
- structlog (если установлен) — структурированные JSON-логи в Graylog
- stdlib logging (fallback) — текущая реализация через LoggerManager

Использование:
    from src.backend.infrastructure.logging.factory import get_logger

    logger.info("Order created", order_id=123, user_id="abc")

Переключение бэкенда:
    from src.backend.infrastructure.logging.factory import configure_logging

    # structlog → Graylog
    configure_logging(backend="structlog")

    # stdlib (по умолчанию)
    configure_logging(backend="stdlib")
"""

from typing import Any

from src.backend.core.config.profile import AppProfileChoices
from src.backend.infrastructure.logging.base import BaseLoggerBackend, LoggerProtocol

__all__ = (
    "configure_logging",
    "get_logger",
    "init_application_logging",
    "init_log_sinks",
    "shutdown_log_sinks",
    "shutdown_logging",
)

_backend: BaseLoggerBackend | None = None


def _create_backend(name: str) -> BaseLoggerBackend:
    if name == "structlog":
        try:
            from src.backend.infrastructure.logging.structlog_backend import (
                StructlogGraylogBackend,
            )

            return StructlogGraylogBackend()
        except ImportError:
            pass

    from src.backend.infrastructure.logging.stdlib_backend import StdlibLoggingBackend

    return StdlibLoggingBackend()


def configure_logging(backend: str = "structlog", **settings: Any) -> BaseLoggerBackend:
    """Настраивает систему логирования.

    Args:
        backend: ``"structlog"`` (default если установлен), ``"stdlib"``
            или ``"auto"`` (structlog если установлен, иначе stdlib).
        **settings: Передаются в backend.configure().

    Returns:
        Настроенный бэкенд.

    Notes:
        Sprint 60 W1 — default изменён на ``"structlog"``: structlog теперь
        primary backend (Graylog + console + disk + correlation/trace/tenant
        binding). Stdlib остаётся fallback если structlog не установлен.
        Compat shim в :class:`StructlogLogger` обеспечивает обратную
        совместимость со stdlib-style ``logger.warning("msg %s", arg)``.

    """
    global _backend

    if _backend is not None:
        _backend.shutdown()

    if backend == "auto":
        try:
            import structlog

            backend = "structlog"
        except ImportError:
            backend = "stdlib"

    _backend = _create_backend(backend)
    _backend.configure(**settings)
    return _backend


def get_logger(name: str) -> LoggerProtocol:
    """Возвращает логгер по имени.

    Если бэкенд ещё не настроен — создаёт stdlib fallback.

    Args:
        name: Имя логгера (например ``"application"``,
            ``"database"``, ``"redis"``).

    Returns:
        Логгер, совместимый с LoggerProtocol.

    """
    global _backend

    if _backend is None:
        # W5 P1-7 (cycle 152, MINIMAX plan): fallback использует auto
        # detection вместо явного stdlib — если structlog установлен
        # (он есть в deps per ADR-0084), prefer structlog. Stdlib fallback
        # остаётся только если structlog import fails. См. ADR-0312.
        _backend = _create_backend(_detect_available_backend())
        _backend.configure()

    return _backend.get_logger(name)


def _detect_available_backend() -> str:
    """Return available backend name (structlog if installed, stdlib otherwise).

    Sprint 60 W1 legacy default: stdlib.
    W5 P1-7 (cycle 152) — switch to auto-detect: prefer structlog if available.
    """
    try:
        import structlog  # noqa: F401 — availability check

        return "structlog"
    except ImportError:
        return "stdlib"


def shutdown_logging() -> None:
    """Корректно завершает систему логирования."""
    global _backend
    if _backend is not None:
        _backend.shutdown()
        _backend = None


def init_log_sinks(profile: AppProfileChoices | None = None, **kwargs: Any) -> None:
    """Инициализировать профильный :class:`SinkRouter`.

    Wave 2.5: должен вызываться один раз на старте приложения (lifespan
    startup). После инициализации structlog-processor :func:`route_to_sinks`
    начнёт пересылать event_dict во все настроенные sink-и (``ConsoleJson``,
    ``DiskRotating``, ``GraylogGelf``).

    Аргументы:
        profile: явный профиль; если ``None`` — берётся из ``APP_PROFILE``.
        **kwargs: проброс параметров в :func:`build_sinks_for_profile`
            (например, ``disk_path``, ``graylog_host``).

    Идемпотентно: повторный вызов заменит активный набор sink-ов
    (старые при этом НЕ закрываются — это ответственность вызывающего
    кода, обычно ``shutdown_log_sinks``).
    """
    from src.backend.infrastructure.logging.router import (
        build_sinks_for_profile,
        configure_router,
    )

    sinks = build_sinks_for_profile(profile, **kwargs)
    configure_router(sinks)


async def shutdown_log_sinks() -> None:
    """Корректно закрыть все sink-и активного :class:`SinkRouter`.

    Должен вызываться в lifespan shutdown ПЕРЕД остановкой остальной
    инфраструктуры — гарантирует, что финальные логи стартапа/штатной
    остановки доедут до sink-ов и буферы сбросятся.

    Если router ещё не инициализирован — no-op.
    """
    from src.backend.infrastructure.logging.router import (
        get_router,
        is_router_configured,
        reset_router,
    )

    if not is_router_configured():
        return
    await get_router().aclose()
    reset_router()


def init_application_logging(
    level: str = "INFO",
    environment: str = "production",
    profile: AppProfileChoices | str | None = None,
    log_dir: str | None = None,
    graylog_host: str | None = None,
    graylog_port: int | None = None,
    graylog_protocol: str | None = None,
    use_settings: bool = True,
) -> BaseLoggerBackend:
    """Единая точка инициализации всего logging-стека приложения.

    Выполняет (в указанном порядке):

    1. :func:`configure_logging` с backend='structlog' (auto-fallback на
       stdlib если structlog не установлен) и переданными ``level``/
        ``environment``. Использует settings-based defaults если ``use_settings``.
    2. :func:`init_log_sinks` с profile из ``APP_PROFILE`` (или явный
        ``profile`` параметр) для активации профильного :class:`SinkRouter`.

    Это centralized entry point — вызывается один раз в
    ``plugins/composition/app_factory.create_app()`` (или lifespan startup)
    ПЕРЕД любым другим кодом приложения, чтобы все логгеры (включая
    ``get_logger(__name__)`` в импортируемых модулях) сразу знали о
    profile-based router-диспетчере.

    Args:
        level: ``DEBUG`` / ``INFO`` / ``WARNING`` / ``ERROR`` / ``CRITICAL``.
            Если ``None`` и ``use_settings=True`` — берётся из ``settings.logging.level``.
        environment: Имя окружения (``"production"``, ``"dev"``, ``"ci"``).
            Если ``None`` и ``use_settings=True`` — из ``settings.app.environment``.
        profile: ``AppProfileChoices.dev_light`` / ``.dev`` / ``.prod``.
            Если ``None`` и ``use_settings=True`` — из ``get_active_profile()``.
        log_dir: Директория для DiskRotatingLogSink. Если ``None`` —
            ``settings.logging.dir_log_name``.
        graylog_host: Graylog GELF host. Если ``None`` — ``settings.logging.host``.
        graylog_port: Graylog GELF port. Если ``None`` — ``settings.logging.port``.
        graylog_protocol: ``"udp"`` / ``"tcp"`` для GELF. Если ``None`` —
            ``"tcp"`` если ``settings.logging.use_tls`` else ``"udp"``.
        use_settings: Если ``True`` (default) — все ``None``-параметры читаются
            из ``settings``. Это рекомендуемый режим (centralized config).

    Raises:
        ImportError: Если structlog выбран как ``backend="structlog"`` но не
            установлен (хотя при ``"auto"`` это fallback на stdlib).

    See Also:
        :func:`configure_logging` — низкоуровневый configure.
        :func:`init_log_sinks` — низкоуровневая инициализация sinks.

    Notes:
        Cycle 161 audit: до этого коммита централизованная инициализация
        отсутствовала — приложение стартовало с lazy default structlog
        backend, но без :class:`SinkRouter` (event_dict не доходили до
        ConsoleJson / DiskRotating / GraylogGelf). См. ADR-0351 § Phase 2.

        Cycle 162 fix: добавлен ``use_settings=True`` mode — все
        None-параметры читаются из settings (LogStorageSettings,
        AppBaseSettings, profile.get_active_profile()). Это устраняет
        gap "centralized config but caller must duplicate settings reads".

        >>> from src.backend.core.logging import init_application_logging
        >>> # Все параметры из settings автоматически (рекомендуется).
        >>> backend = init_application_logging()
        >>>
        >>> # Или явное переопределение (override settings):
        >>> backend = init_application_logging(level="DEBUG", environment="dev")
    """
    global _backend

    # Cycle 162 fix: если use_settings=True и параметр None — читаем из settings.
    if use_settings:
        try:
            from src.backend.core.config.profile import get_active_profile
            from src.backend.core.config.settings import settings as _settings

            if level == "INFO":  # default
                level = _settings.logging.level
            if environment == "production":  # default
                environment = _settings.app.environment
            if profile is None:
                profile = get_active_profile()
            if log_dir is None:
                log_dir = _settings.logging.dir_log_name
            if graylog_host is None:
                graylog_host = _settings.logging.host
            if graylog_port is None:
                graylog_port = _settings.logging.port
            if graylog_protocol is None:
                graylog_protocol = "tcp" if _settings.logging.use_tls else "udp"
        except (ImportError, AttributeError):
            # settings не доступны (например, в unit-test минимальном окружении) —
            # используем явные defaults. Backend уже инициализирован с ними.
            pass

    # Step 1: configure_logging с явными параметрами (level, environment).
    backend = configure_logging(
        backend="auto",
        level=level,
        environment=environment,
    )

    # Step 2: init_log_sinks с profile-based router.
    profile_arg: AppProfileChoices | None
    if isinstance(profile, str):
        try:
            profile_arg = AppProfileChoices(profile)
        except ValueError:
            profile_arg = None
    else:
        profile_arg = profile

    sinks_kwargs: dict[str, Any] = {}
    if log_dir is not None:
        # build_sinks_for_profile ожидает disk_path (полный путь к файлу),
        # а не директорию. Settings даёт имя директории — компонуем путь.
        disk_filename = "app.jsonl"
        if log_dir and not log_dir.endswith("/"):
            log_dir = log_dir + "/"
        sinks_kwargs["disk_path"] = f"{log_dir}{disk_filename}" if log_dir else "logs/app.jsonl"
    if graylog_host is not None:
        sinks_kwargs["graylog_host"] = graylog_host
    if graylog_port is not None:
        sinks_kwargs["graylog_port"] = graylog_port
    if graylog_protocol is not None:
        sinks_kwargs["graylog_protocol"] = graylog_protocol

    init_log_sinks(profile=profile_arg, **sinks_kwargs)
    return backend
