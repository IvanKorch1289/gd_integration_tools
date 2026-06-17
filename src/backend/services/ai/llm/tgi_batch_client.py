"""HuggingFace TGI batch inference client (S13 K4 W2).

Использует ``OutboundHttpClient`` (WAF strict policy R-V15-5) для
параллельных HTTP-запросов к TGI-серверу. Capability:
``net.outbound.tgi_server:external``.
"""

from __future__ import annotations

import asyncio
from typing import Any

from src.backend.core.logging import get_logger

__all__ = ("TgiBatchClient",)

logger = get_logger(__name__)


class TgiBatchClient:
    """TGI HTTP-client с batch parallel execution."""

    def __init__(
        self,
        *,
        base_url: str,
        http_client: Any,
        concurrency: int = 10,
        timeout_seconds: float = 60.0,
    ) -> None:
        self._url = base_url.rstrip("/")
        self._client = http_client
        self._semaphore = asyncio.Semaphore(concurrency)
        self._timeout = timeout_seconds

    async def _single_completion(
        self, prompt: str, *, max_tokens: int, temperature: float
    ) -> str:
        async with self._semaphore:
            payload = {
                "inputs": prompt,
                "parameters": {
                    "max_new_tokens": max_tokens,
                    "temperature": temperature,
                    "return_full_text": False,
                },
            }
            response = await self._client.post(
                f"{self._url}/generate", json=payload, timeout=self._timeout
            )
            data = response.json() if hasattr(response, "json") else response
            if isinstance(data, list) and data:
                return str(data[0].get("generated_text", ""))
            if isinstance(data, dict):
                return str(data.get("generated_text", ""))
            return ""

    async def batch_completions(
        self,
        prompts: list[str],
        *,
        model: str,
        max_tokens: int = 256,
        temperature: float = 0.0,
    ) -> list[str]:
        if not prompts:
            return []
        # S163 W28: asyncio.TaskGroup (Python 3.11+) вместо asyncio.gather
        # для structured параллелизма. Преимущества:
        # - Если одна task raises, остальные отменяются (clean cancellation)
        # - ExceptionGroup вместо first exception (Py3.11+)
        async with asyncio.TaskGroup() as tg:
            tg_tasks = [
                tg.create_task(
                    self._single_completion(
                        p, max_tokens=max_tokens, temperature=temperature
                    )
                )
                for p in prompts
            ]
        return [t.result() for t in tg_tasks]  # type: ignore[union-attr]  # noqa

    async def _single_embedding(self, text: str) -> list[float]:
        async with self._semaphore:
            payload = {"inputs": text}
            response = await self._client.post(
                f"{self._url}/embeddings", json=payload, timeout=self._timeout
            )
            data = response.json() if hasattr(response, "json") else response
            if isinstance(data, list) and data and isinstance(data[0], list):
                return list(data[0])
            if isinstance(data, dict) and "embedding" in data:
                return list(data["embedding"])
            return []

    async def batch_embeddings(
        self, texts: list[str], *, model: str
    ) -> list[list[float]]:
        if not texts:
            return []
        tasks = [self._single_embedding(t) for t in texts]
        return await asyncio.gather(*tasks)
