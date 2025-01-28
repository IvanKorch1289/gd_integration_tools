import logging
from logging.handlers import (
    QueueHandler,
    QueueListener,
    TimedRotatingFileHandler,
)

import graypy
import socket
from queue import Queue

from app.core.settings import settings


__all__ = (
    "app_logger",
    "db_logger",
    "fs_logger",
    "mail_logger",
    "scheduler_logger",
    "request_logger",
    "kafka_logger",
    "log_user_activity",
)


class ContextFilter(logging.Filter):
    """Добавляет общие контекстные поля во все записи логов"""

    def filter(self, record: logging.LogRecord) -> bool:

        record.environment = settings.app_environment
        record.hostname = socket.gethostname()
        record.user_id = getattr(record, "user_id", "system")
        record.action = getattr(record, "action", "none")
        record.logger = record.name
        return True


class SafeFormatter(logging.Formatter):
    """Форматтер с проверкой наличия обязательных полей"""

    def format(self, record: logging.LogRecord) -> str:
        for field in settings.logging_settings.log_required_fields:
            if not hasattr(record, field):
                setattr(record, field, "unknown")
        return super().format(record)


def setup_logging() -> None:
    """Инициализация системы логирования с асинхронной отправкой в Graylog"""
    log_config = settings.logging_settings
    formatter = SafeFormatter(
        "%(asctime)s - %(name)s - %(levelname)s - %(message)s "
        "[%(environment)s@%(hostname)s] User:%(user_id)s Action:%(action)s"
    )

    # Создаем очередь для асинхронной обработки
    log_queue = Queue()

    # Обработчики для Graylog
    graylog_handlers = []
    if log_config.log_host and log_config.log_udp_port:
        if log_config.log_use_tls:
            handler = graypy.GELFTLSHandler(
                log_config.log_host,
                log_config.log_udp_port,
                ca_certs=log_config.log_ca_certs,
            )
        else:
            handler = graypy.GELFUDPHandler(
                log_config.log_host, log_config.log_udp_port
            )
        handler.addFilter(ContextFilter())
        graylog_handlers.append(handler)

    # Файловый обработчик
    file_handler = TimedRotatingFileHandler(
        filename="app.log",
        when="midnight",  # Ротация ежедневно
        interval=1,
        backupCount=7,  # Хранить 7 архивных копий
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)
    file_handler.addFilter(ContextFilter())

    # Консольный обработчик
    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    console_handler.addFilter(ContextFilter())

    # Создаем QueueListener с обработчиками
    all_handlers = [*graylog_handlers, file_handler]
    if settings.app_debug:
        all_handlers.append(console_handler)

    queue_listener = QueueListener(log_queue, *all_handlers, respect_handler_level=True)
    queue_listener.start()

    # Настройка логгеров
    for logger_cfg in LOGGERS_CONFIG:
        logger = logging.getLogger(logger_cfg["name"])
        logger.propagate = False
        logger.setLevel(log_config.log_level.upper())

        # Удаляем старые обработчики
        for handler in logger.handlers[:]:
            logger.removeHandler(handler)

        # Добавляем асинхронный обработчик очереди
        logger.addHandler(QueueHandler(log_queue))


def log_user_activity(
    user_id: str, action: str, logger_name: str = "application", **additional_info
) -> None:
    """Логирование действий пользователя"""
    logger = logging.getLogger(logger_name)
    extra = {"user_id": user_id, "action": action, **additional_info}
    logger.info("User activity: %s", action, extra=extra, stacklevel=2)


LOGGERS_CONFIG = [
    {"name": "application", "facility": "app"},
    {"name": "database", "facility": "db"},
    {"name": "storage", "facility": "storage"},
    {"name": "mail", "facility": "mail"},
    {"name": "scheduler", "facility": "scheduler"},
    {"name": "request", "facility": "request"},
    {"name": "kafka", "facility": "kafka"},
]

# Инициализация логгеров
setup_logging()

# Экспорт логгеров
app_logger = logging.getLogger("application")
db_logger = logging.getLogger("database")
fs_logger = logging.getLogger("storage")
mail_logger = logging.getLogger("mail")
scheduler_logger = logging.getLogger("scheduler")
request_logger = logging.getLogger("request")
kafka_logger = logging.getLogger("kafka")
