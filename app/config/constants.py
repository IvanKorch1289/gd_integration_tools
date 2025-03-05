from asyncio import TimeoutError
from datetime import timedelta, timezone
from pathlib import Path

from aiohttp import ClientError


__all__ = ("ROOT_DIR",)


ROOT_DIR = Path(__file__).parent.parent.parent

# Константа для временной зоны (Москва)
MOSCOW_TZ = timezone(timedelta(hours=3))

RETRY_EXCEPTIONS = (ClientError, TimeoutError)

CHECK_SERVICES_JOB = {"name": "check_all_services_job", "minutes": 60}

PREFECT_SERVER_COMMAND = "prefect server start"
PREFECT_WORKER_COMMAND = "prefect agent start -q 'default'"

# Для воркфлоу заказов в СКБ-Техно
INITIAL_DELAY = 1800  # 30 minutes
RETRY_DELAY = 900  # 15 minutes
MAX_RESULT_ATTEMPTS = 4

# Коды ошибок Postgres, при которых будет выполняться повторные попытки
RETRIABLE_DB_CODES = {
    "08000",
    "08003",
    "08006",
    "08001",
    "08004",
    "08007",
    "40001",
    "40P01",
    "55006",
    "55P03",
    "53300",
    "57P01",
    "57P02",
    "57P03",
    "58000",
}
