from pathlib import Path

import aiohttp
import asyncio


__all__ = ("ROOT_DIR",)


ROOT_DIR = Path(__file__).parent.parent.parent

RETRY_EXCEPTIONS = (aiohttp.ClientError, asyncio.TimeoutError)

MAX_ATTEMPTS_FOR_TASKS = 5
DELAY_BEFORE_ATTEMPTS = 20
RETRY_POLICY = {
    "max_retries": MAX_ATTEMPTS_FOR_TASKS,  # Максимальное количество попыток
    "delay": DELAY_BEFORE_ATTEMPTS,  # Задержка между попытками в секундах
}
