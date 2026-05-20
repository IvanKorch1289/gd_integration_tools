"""Lakera Guard async client (Sprint 11 K1 W2).

Async httpx-client поверх ``core.net.migration_helper.make_http_client``
(WAF фасад при ``waf_outbound_via_facade``; capability
``ai.guardrails.lakera``).

При отсутствии ``LAKERA_API_KEY`` клиент возвращает no-op результат
(``flagged=False``) — fail-open для dev_light окружения.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any

import httpx

__all__ = ("LakeraClient", "LakeraResult")

_DEFAULT_BASE = "https://api.lakera.ai/v2"


@dataclass(frozen=True, slots=True)
class LakeraResult:
    """Результат одного скана Lakera Guard.

    Attributes:
        flagged: True, если provider пометил входной prompt как небезопасный.
        score: Числовая оценка [0..1]; больше — выше уверенность detector'а.
        categories: Категории срабатывания (``prompt_injection``, ``pii``,
            ``hate_speech``, ...) — список dict'ов из ответа API.
    """

    flagged: bool
    score: float
    categories: list[dict[str, Any]]


class LakeraClient:
    """Async-обёртка над Lakera Guard prompt-injection / PII detector.

    Args:
        api_key: Lakera API token. Если ``None`` — читается из env
            ``LAKERA_API_KEY``; при отсутствии — клиент в no-op режиме.
        base_url: URL API; default ``https://api.lakera.ai/v2``.
        timeout: HTTP timeout (sec); default 5.
    """

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str = _DEFAULT_BASE,
        timeout: float = 5.0,
    ) -> None:
        self._api_key = api_key or os.environ.get("LAKERA_API_KEY")
        self._base_url = base_url.rstrip("/")
        self._timeout = timeout

    async def screen(self, text: str, *, breakdown: bool = True) -> LakeraResult:
        """Отправить prompt в Lakera Guard и вернуть структурированный результат.

        Args:
            text: Произвольный prompt / user-input.
            breakdown: Если True, попросить provider вернуть
                разбивку по категориям (default True).

        Returns:
            :class:`LakeraResult`. Если ``api_key`` отсутствует — возвращает
            no-op (``flagged=False, score=0.0, categories=[]``).
        """
        if not self._api_key:
            return LakeraResult(flagged=False, score=0.0, categories=[])

        from src.backend.core.net.migration_helper import make_http_client

        payload: dict[str, Any] = {
            "input": text,
            "breakdown": bool(breakdown),
        }
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }
        async with make_http_client(
            plugin="services.ai.guardrails.lakera",
            base_url=self._base_url,
            timeout=self._timeout,
            headers=headers,
        ) as client:
            response: httpx.Response = await client.post(
                "/guard", json=payload
            )
            response.raise_for_status()
            data = response.json()

        return LakeraResult(
            flagged=bool(data.get("flagged", False)),
            score=float(data.get("score", 0.0) or 0.0),
            categories=list(data.get("breakdown") or data.get("categories") or []),
        )
