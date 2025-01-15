import logging

import graypy

from backend.core.settings import settings as s


# Настройки для Graylog
GRAYLOG_HOST = s.logging_settings.log_host
GRAYLOG_PORT = s.logging_settings.log_udp_port

# Создаем список логгеров и их настроек
LOGGERS = [
    {"name": "application", "facility": "application"},
    {"name": "database", "facility": "database"},
    {"name": "storage", "facility": "file_system"},
    {"name": "mail", "facility": "mail_server"},
    {"name": "scheduler", "facility": "scheduler"},
]

# Форматирование логов
formatter = logging.Formatter("%(asctime)s - %(name)s - %(levelname)s - %(message)s")

# Функция для настройки логгеров


def setup_loggers():
    for logger_config in LOGGERS:
        # Создаем обработчик для Graylog
        graylog_handler = graypy.GELFUDPHandler(
            host=GRAYLOG_HOST,
            port=GRAYLOG_PORT,
            facility=logger_config["facility"],
        )
        graylog_handler.setFormatter(formatter)

        # Настраиваем логгер
        logger = logging.getLogger(logger_config["name"])
        logger.setLevel(logging.DEBUG)
        logger.addHandler(graylog_handler)


# Вызываем функцию настройки логгеров
setup_loggers()

# Создаем логгеры для использования в других частях кода
app_logger = logging.getLogger("application")
db_logger = logging.getLogger("database")
fs_logger = logging.getLogger("storage")
mail_logger = logging.getLogger("mail")
scheduler_logger = logging.getLogger("scheduler")
