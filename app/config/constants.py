from asyncio import TimeoutError
from datetime import timedelta, timezone
from pathlib import Path
from typing import Set

from aiohttp import ClientError
from dataclasses import dataclass, field


__all__ = ("consts", "Constants")


@dataclass
class Constants:
    """
    Класс для хранения констант.

    Атрибуты:
        ROOT_DIR (Path): Корневая директория проекта.
        MOSCOW_TZ (timezone): Временная зона для Москвы (UTC+3).
        RETRY_EXCEPTIONS (tuple): Исключения, при которых следует повторять запросы.
        CHECK_SERVICES_JOB (dict): Настройки задачи проверки сервисов.
        PREFECT_SERVER_COMMAND (str): Команда для запуска сервера Prefect.
        PREFECT_WORKER_COMMAND (str): Команда для запуска воркера Prefect.
        INITIAL_DELAY (int): Начальная задержка перед повторной попыткой (в секундах).
        RETRY_DELAY (int): Задержка между повторными попытками (в секундах).
        MAX_RESULT_ATTEMPTS (int): Максимальное количество попыток получения результата.
        RETRIABLE_DB_CODES (Set[str]): Коды ошибок PostgreSQL, при которых следует повторять операцию.
    """

    ROOT_DIR: Path = Path(__file__).parent.parent.parent
    MOSCOW_TZ: timezone = timezone(timedelta(hours=3))
    RETRY_EXCEPTIONS: tuple = (ClientError, TimeoutError)
    CHECK_SERVICES_JOB: dict = field(
        default_factory=lambda: {
            "name": "check_all_services_job",
            "minutes": 60,
        }
    )
    PREFECT_SERVER_COMMAND: str = "prefect server start"
    PREFECT_WORKER_COMMAND: str = "prefect agent start -q 'default'"
    INITIAL_DELAY: int = 3600  # 60 минут
    RETRY_DELAY: int = 1800  # 30 минут
    MAX_RESULT_ATTEMPTS: int = 4
    RETRIABLE_DB_CODES: Set[str] = field(
        default_factory=lambda: {
            # Ошибки, связанные с подключением
            "08000",
            "08003",
            "08006",
            "08001",
            "08004",
            "08007",
            # Конфликты транзакций
            "40001",
            "40P01",
            # Ограничения ресурсов
            "55006",
            "55P03",
            "53300",
            # Системные ошибки
            "57P01",
            "57P02",
            "57P03",
            # Прочие ошибки
            "58000",
        }
    )


# Экземпляр конфигурации
consts = Constants()
