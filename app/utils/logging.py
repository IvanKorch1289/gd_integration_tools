import logging
from logging.handlers import (
    QueueHandler,
    QueueListener,
    TimedRotatingFileHandler,
)
from typing import List, Optional

import graypy
import socket
from queue import Queue

from app.config.settings import LogStorageSettings, settings


__all__ = (
    "LoggerManager",
    "app_logger",
    "db_logger",
    "fs_logger",
    "mail_logger",
    "scheduler_logger",
    "request_logger",
    "kafka_logger",
)


class LoggerManager:
    """Класс для управления конфигурацией логирования приложения."""

    class ContextFilter(logging.Filter):
        """Добавляет общие контекстные поля в записи логов."""

        def __init__(self, environment: str, hostname: str):
            super().__init__()
            self.environment = environment
            self.hostname = hostname

        def filter(self, record: logging.LogRecord) -> bool:
            record.environment = self.environment
            record.hostname = self.hostname
            record.user_id = getattr(record, "user_id", "system")
            record.action = getattr(record, "action", "none")
            record.logger = record.name
            return True

    class SafeFormatter(logging.Formatter):
        """Форматирует записи логов, гарантируя наличие обязательных полей."""

        def __init__(self, fmt: str, required_fields: List[str]):
            super().__init__(fmt)
            self.required_fields = required_fields

        def format(self, record: logging.LogRecord) -> str:
            for field in self.required_fields:
                if not hasattr(record, field):
                    setattr(record, field, "unknown")
            return super().format(record)

    def __init__(
        self,
        log_config: LogStorageSettings,
        environment: str,
        hostname: str,
        debug: bool = False,
    ):
        """
        Инициализация менеджера логирования.

        :param log_config: Конфигурация логирования
        :param environment: Окружение приложения (prod, dev и т.д.)
        :param hostname: Имя хоста
        :param debug: Режим отладки
        """
        self.log_config = log_config
        self.environment = environment
        self.hostname = hostname
        self.debug = debug

        self.log_queue = Queue()
        self.queue_listener: Optional[QueueListener] = None
        self.handlers: List[logging.Handler] = []

        # Инициализация компонентов логирования
        self._setup_formatter()
        self._setup_handlers()
        self._setup_queue_listener()
        self._configure_loggers()
        self._init_logger_instances()

    def _setup_formatter(self) -> None:
        """Инициализация форматтера логов."""
        log_format = (
            "%(asctime)s - %(name)s - %(levelname)s - %(message)s "
            "[%(environment)s@%(hostname)s] User:%(user_id)s Action:%(action)s"
        )
        self.formatter = self.SafeFormatter(
            fmt=log_format, required_fields=self.log_config.log_required_fields
        )

    def _setup_handlers(self) -> None:
        """Настройка обработчиков логирования."""
        # Graylog обработчики
        if self._graylog_enabled:
            self.handlers.extend(self._create_graylog_handlers())

        # Файловый обработчик
        file_handler = self._create_file_handler()
        self.handlers.append(file_handler)

        # Консольный обработчик (только в режиме отладки)
        if self.debug:
            console_handler = self._create_console_handler()
            self.handlers.append(console_handler)

    def _setup_queue_listener(self) -> None:
        """Запуск асинхронного обработчика логов."""
        self.queue_listener = QueueListener(
            self.log_queue, *self.handlers, respect_handler_level=True
        )
        self.queue_listener.start()

    def _configure_loggers(self) -> None:
        """Настройка всех логгеров из конфигурации."""
        for logger_cfg in self.settings.log_loggers_config:
            logger = logging.getLogger(logger_cfg["name"])
            logger.propagate = False
            logger.setLevel(self.log_config.log_level.upper())
            self._reset_handlers(logger)
            logger.addHandler(QueueHandler(self.log_queue))

    def _init_logger_instances(self) -> None:
        """Инициализация атрибутов логгеров для удобного доступа."""
        for logger_cfg in self.settings.loggers_config:
            logger_name = logger_cfg["name"]
            setattr(self, f"{logger_name}_logger", logging.getLogger(logger_name))

    @property
    def _graylog_enabled(self) -> bool:
        """Проверка активации Graylog."""
        return bool(self.log_config.log_host and self.log_config.log_udp_port)

    def _create_graylog_handlers(self) -> List[logging.Handler]:
        """Создание обработчиков для Graylog."""
        handler_class = (
            graypy.GELFTLSHandler
            if self.log_config.log_use_tls
            else graypy.GELFUDPHandler
        )

        handler = handler_class(
            self.log_config.log_host,
            self.log_config.log_udp_port,
            **(
                {"ca_certs": self.log_config.log_ca_certs}
                if self.log_config.log_use_tls
                else {}
            ),
        )

        handler.addFilter(self.ContextFilter(self.environment, self.hostname))
        return [handler]

    def _create_file_handler(self) -> TimedRotatingFileHandler:
        """Создание файлового обработчика с ротацией."""
        handler = TimedRotatingFileHandler(
            filename="app.log",
            when="midnight",
            interval=1,
            backupCount=7,
            encoding="utf-8",
        )
        handler.setFormatter(self.formatter)
        handler.addFilter(self.ContextFilter(self.environment, self.hostname))
        return handler

    def _create_console_handler(self) -> logging.StreamHandler:
        """Создание консольного обработчика."""
        handler = logging.StreamHandler()
        handler.setFormatter(self.formatter)
        handler.addFilter(self.ContextFilter(self.environment, self.hostname))
        return handler

    @staticmethod
    def _reset_handlers(logger: logging.Logger) -> None:
        """Удаление всех существующих обработчиков у логгера."""
        for handler in logger.handlers[:]:
            logger.removeHandler(handler)

    def log_user_activity(
        self,
        user_id: str,
        action: str,
        logger_name: str = "application",
        **additional_info,
    ) -> None:
        """
        Логирование действий пользователя.

        :param user_id: Идентификатор пользователя
        :param action: Выполненное действие
        :param logger_name: Имя логгера (по умолчанию 'application')
        :param additional_info: Дополнительные поля для логирования
        """
        logger = logging.getLogger(logger_name)
        extra = {"user_id": user_id, "action": action, **additional_info}
        logger.info("User activity: %s", action, extra=extra, stacklevel=2)

    async def health_check_graylog(self) -> bool:
        """Проверка доступности Graylog."""
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
                sock.connect((self.log_config.log_host, self.log_config.log_udp_port))
                sock.sendall(b"Healthcheck test message")
            return True
        except OSError as exc:
            # Адаптируйте обработку ошибок под ваш фреймворк
            raise RuntimeError(f"Graylog connection failed: {exc}") from exc

    def shutdown(self) -> None:
        """Безопасное завершение работы менеджера логирования."""
        if self.queue_listener:
            self.queue_listener.stop()


# Инициализация менеджера логирования
log_manager = LoggerManager(
    log_config=settings.logging,
    environment=settings.app_environment,
    hostname=socket.gethostname(),
    debug=settings.app_debug,
)

# Получение логгеров
app_logger = log_manager.application_logger
db_logger = log_manager.database_logger
fs_logger = log_manager.storage_logger
mail_logger = log_manager.mail_logger
scheduler_logger = log_manager.scheduler_logger
request_logger = log_manager.request_logger
kafka_logger = log_manager.kafka_logger
