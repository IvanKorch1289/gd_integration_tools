"""Rebuff prompt-injection detector client (Sprint 11 K1 W2).

Async-обёртка над Rebuff REST API. Аналогична LakeraClient — без API key
возвращает no-op результат (``injected=False``).
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

import httpx

__all__ = ("RebuffClient", "RebuffResult")

_DEFAULT_BASE = "https://www.rebuff.ai/api"


@dataclass(frozen=True, slots=True)
class RebuffResult:
    """Результат одного запроса Rebuff.

    Attributes:
        injected: True, если detector нашёл prompt-injection.
        score: Heuristic+model score [0..1].
        metadata: Дополнительные поля из ответа (heuristic_score,
            model_score, run_heuristics, run_vector_db).
    """

    injected: bool
    score: float
    metadata: dict[str, Any]


class RebuffClient:
    """Async-клиент Rebuff prompt-injection detector.

    Args:
        api_key: Rebuff API key. Если None — читается из env
            ``REBUFF_API_KEY``; при отсутствии — no-op mode.
        base_url: URL API; default ``https://www.rebuff.ai/api``.
        timeout: HTTP timeout (sec); default 5.
    """

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str = _DEFAULT_BASE,
        timeout: float = 5.0,
    ) -> None:
        self._api_key = api_key or os.environ.get("REBUFF_API_KEY")
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout

    async def detect(self, text: str) -> RebuffResult:
        """Отправить prompt в Rebuff и вернуть результат detection."""
        if not self._api_key:
            return RebuffResult(injected=False, score=0.0, metadata={})

        from src.backend.core.net.migration_helper import make_http_client

        payload = {"userInput": text}
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }
        async with make_http_client(
            plugin="services.ai.guardrails.rebuff",
            base_url=self._base_url,
            timeout=self._timeout,
            headers=headers,
        ) as client:
            response: httpx.Response = await client.post("/detect", json=payload)
            response.raise_for_status()
            data = response.json()

        heuristic = float(data.get("heuristicScore", 0.0) or 0.0)
        model = float(data.get("modelScore", 0.0) or 0.0)
        score = max(heuristic, model)
        return RebuffResult(
            injected=bool(data.get("injectionDetected", score > 0.0)),
            score=score,
            metadata={
                "heuristic_score": heuristic,
                "model_score": model,
                "run_heuristics": data.get("runHeuristicCheck"),
                "run_vector_db": data.get("runVectorCheck"),
            },
        )
