from __future__ import annotations
import asyncio
from abc import ABC, abstractmethod
from collections.abc import AsyncGenerator, Mapping
from contextlib import asynccontextmanager
from functools import lru_cache
from logging import DEBUG
from time import monotonic
from typing import Any, BinaryIO, TypedDict

import httpx
from tenacity import (
    RetryError,
    before_sleep_log,
    retry,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential,
)

from src.backend.core.config.constants import consts
from src.backend.core.config.settings import settings
from src.backend.core.utils.circuit_breaker import get_circuit_breaker
from src.backend.core.utils.task_registry import get_task_registry
from src.backend.dsl.codec.json import json_dumps
from src.backend.infrastructure.logging.factory import get_logger

async def get_http_client() -> AsyncGenerator[HttpClient]:
    client = HttpClient()
    yield client

def get_http_client_dependency() -> HttpClient:
    """Lazy singleton глобального ``HttpClient`` (Wave 6.1)."""
    return HttpClient()

