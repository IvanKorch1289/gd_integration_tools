from pathlib import Path

import aiohttp
import asyncio


__all__ = ("ROOT_DIR",)


ROOT_DIR = Path(__file__).parent.parent.parent

RETRY_EXCEPTIONS = (aiohttp.ClientError, asyncio.TimeoutError)
