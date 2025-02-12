from pathlib import Path

import aiohttp
import asyncio


__all__ = ("ROOT_DIR",)


ROOT_DIR = Path(__file__).parent.parent.parent

RETRY_EXCEPTIONS = (aiohttp.ClientError, asyncio.TimeoutError)

MAX_ATTEMPTS_SEND_ORDER_TO_SKB = 5
MAX_ATTEMPTS_GET_ORDER_RESULT_FROM_SKB = 5
