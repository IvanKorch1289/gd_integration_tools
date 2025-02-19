import asyncio
from pathlib import Path

import aiohttp


__all__ = ("ROOT_DIR",)


ROOT_DIR = Path(__file__).parent.parent.parent

RETRY_EXCEPTIONS = (aiohttp.ClientError, asyncio.TimeoutError)

CHECK_SERVICES_JOB = {"name": "check_all_services_job", "minutes": 60}
