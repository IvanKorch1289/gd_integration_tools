from logging import (
    Filter,
    Formatter,
    Handler,
    Logger,
    LogRecord,
    StreamHandler,
    getLogger,
)
from logging.handlers import (
    QueueHandler,
    QueueListener,
    TimedRotatingFileHandler,
)
from socket import gethostname
from typing import List, Optional

from app.config.settings import LogStorageSettings, settings
from app.infra.clients.logger import GraylogHandler, graylog_handler


__all__ = (
    "app_logger",
    "db_logger",
    "fs_logger",
    "smtp_logger",
    "scheduler_logger",
    "request_logger",
    "tasks_logger",
    "redis_logger",
    "stream_logger",
)


class LoggerManager:
    """Централизованный менеджер конфигурации логирования с поддержкой нескольких обработчиков."""

    class ContextFilter(Filter):
        """Добавляет общие контекстные поля в записи логов."""

        def __init__(self, environment: str, hostname: str):
            super().__init__()
            self.environment = environment
            self.hostname = hostname

        def filter(self, record: LogRecord) -> bool:
            """Обогащает записи логов контекстной информацией.

            Аргументы:
                record (LogRecord): Запись лога

            Возвращает:
                bool: Всегда True, так как фильтр только добавляет данные
            """
            record.environment = self.environment
            record.hostname = self.hostname
            record.user_id = getattr(record, "user_id", "system")
            record.action = getattr(record, "action", "none")
            record.logger = record.name
            return True

    class SafeFormatter(Formatter):
        """Гарантирует наличие обязательных полей в записях логов."""

        def __init__(self, fmt: str, required_fields: List[str]):
            """
            Инициализирует форматтер с обязательными полями.

            Аргументы:
                fmt (str): Строка формата лога
                required_fields (List[str]): Обязательные поля для каждой записи
            """
            super().__init__(fmt)
            self.required_fields = required_fields

        def format(self, record: LogRecord) -> str:
            """Форматирует запись лога с гарантией наличия обязательных полей.

            Аргументы:
                record (LogRecord): Запись лога

            Возвращает:
                str: Отформатированная строка лога
            """
            for field in self.required_fields:
                if not hasattr(record, field):
                    setattr(record, field, "unknown")
            return super().format(record)

    def __init__(
        self,
        log_config: LogStorageSettings,
        environment: str,
        hostname: str,
        handler: GraylogHandler,
        debug: bool = False,
    ):
        """
        Инициализирует менеджер логирования.

        Аргументы:
            log_config (LogStorageSettings): Конфигурация логирования
            environment (str): Окружение приложения (prod, dev и т.д.)
            hostname (str): Имя хоста сервера
            handler (GraylogHandler): Обработчик Graylog
            debug (bool): Флаг режима отладки
        """
        from queue import Queue

        self.log_config = log_config
        self.environment = environment
        self.hostname = hostname
        self.debug = debug

        self.log_queue = Queue()
        self.queue_listener: Optional[QueueListener] = None
        self.handlers: List[Handler] = []
        self.graylog: GraylogHandler = handler

        self._setup_components()
        self._init_logger_instances()

    def _setup_components(self) -> None:
        """Настраивает все компоненты системы логирования."""
        self._setup_formatter()
        self._setup_handlers()
        self._setup_queue_listener()
        self._configure_loggers()

    def _setup_formatter(self) -> None:
        """Инициализирует форматтер логов с обязательными полями."""
        log_format = (
            "%(asctime)s - %(name)s - %(levelname)s - %(message)s "
            "[%(environment)s@%(hostname)s] User:%(user_id)s Action:%(action)s"
        )
        self.formatter = self.SafeFormatter(
            fmt=log_format, required_fields=self.log_config.required_fields
        )

    def _setup_handlers(self) -> None:
        """Настраивает все обработчики логов."""
        # Обработчик Graylog
        if self.graylog.enabled:
            gl_handler = self.graylog.connect()
            if gl_handler:
                gl_handler.addFilter(
                    self.ContextFilter(self.environment, self.hostname)
                )
                self.handlers.append(gl_handler)

        # Обработчик файлов
        if settings.app.environment == "development":
            self.handlers.append(self._create_file_handler())

        # Обработчик консоли
        if self.debug:
            self.handlers.append(self._create_console_handler())

    def _create_file_handler(self) -> TimedRotatingFileHandler:
        """Настраивает ротируемый по времени файловый обработчик."""
        import os

        log_dir = self.log_config.dir_log_name
        os.makedirs(log_dir, exist_ok=True)

        handler = TimedRotatingFileHandler(
            filename=os.path.join(log_dir, self.log_config.name_log_file),
            when="midnight",
            interval=1,
            backupCount=7,
            encoding="utf-8",
        )
        handler.setFormatter(self.formatter)
        handler.addFilter(self.ContextFilter(self.environment, self.hostname))
        return handler

    def _create_console_handler(self) -> StreamHandler:
        """Настраивает обработчик вывода в консоль."""
        handler = StreamHandler()
        handler.setFormatter(self.formatter)
        handler.addFilter(self.ContextFilter(self.environment, self.hostname))
        return handler

    def _setup_queue_listener(self) -> None:
        """Инициализирует асинхронную обработку логов."""
        self.queue_listener = QueueListener(
            self.log_queue, *self.handlers, respect_handler_level=True
        )
        self.queue_listener.start()

    def _configure_loggers(self) -> None:
        """Настраивает все зарегистрированные логгеры."""
        for logger_cfg in self.log_config.conf_loggers:
            logger = getLogger(logger_cfg["name"])
            logger.propagate = False
            logger.setLevel(self.log_config.level.upper())
            self._reset_handlers(logger)
            logger.addHandler(QueueHandler(self.log_queue))

    def _init_logger_instances(self) -> None:
        """Создает экземпляры логгеров как атрибуты класса."""
        for logger_cfg in self.log_config.conf_loggers:
            logger_name = logger_cfg["name"]
            setattr(self, f"{logger_name}_logger", getLogger(logger_name))

    @staticmethod
    def _reset_handlers(logger: Logger) -> None:
        """Удаляет существующие обработчики из логгера."""
        for handler in logger.handlers[:]:
            logger.removeHandler(handler)

    def shutdown(self) -> None:
        """Безопасно завершает работу системы логирования."""
        if self.queue_listener:
            self.queue_listener.stop()
        self.graylog.close()


# Инициализация системы логирования
log_manager = LoggerManager(
    log_config=settings.logging,
    environment=settings.app.environment,
    hostname=gethostname(),
    handler=graylog_handler,
    debug=settings.app.debug_mode,
)

# Экспорт общих логгеров
app_logger = log_manager.application_logger  # type: ignore
db_logger = log_manager.database_logger  # type: ignore
fs_logger = log_manager.storage_logger  # type: ignore
smtp_logger = log_manager.smtp_logger  # type: ignore
scheduler_logger = log_manager.scheduler_logger  # type: ignore
request_logger = log_manager.request_logger  # type: ignore
tasks_logger = log_manager.tasks_logger  # type: ignore
redis_logger = log_manager.redis_logger  # type: ignore
stream_logger = log_manager.stream_logger  # type: ignore
grpc_logger = log_manager.grpc_logger  # type: ignore
