from asyncio import TimeoutError
from pathlib import Path

from aiohttp import ClientError


__all__ = ("ROOT_DIR",)


ROOT_DIR = Path(__file__).parent.parent.parent

RETRY_EXCEPTIONS = (ClientError, TimeoutError)

CHECK_SERVICES_JOB = {"name": "check_all_services_job", "minutes": 60}

PREFECT_SERVER_COMMAND = "prefect server start"
PREFECT_WORKER_COMMAND = "prefect agent start -q 'default'"
