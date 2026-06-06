"""Базовый HTTP-клиент с retry, timeout и JWT token propagation.

Sprint 45 W2: добавлена реальная retry-логика с exponential backoff.
Ранее ``max_retries=3`` сохранялось, но НЕ использовалось (W6 fix).
"""

from __future__ import annotations

import random
import time
from typing import Any

import httpx

from src.frontend.streamlit_app.config import get_api_base_url

__all__ = ("BaseAPIClient", "get_base_client")

_BASE_URL = get_api_base_url()


# HTTP status codes that should trigger a retry.
# 5xx = server error (transient), 408 = request timeout, 429 = rate limit.
_RETRYABLE_STATUS_CODES: frozenset[int] = frozenset({408, 429, 500, 502, 503, 504})

# Initial backoff (seconds). Doubles on each retry: 0.5, 1.0, 2.0, 4.0, ...
_DEFAULT_INITIAL_BACKOFF: float = 0.5

# Maximum backoff (seconds) per attempt.
_MAX_BACKOFF: float = 8.0


class BaseAPIClient:
    """Базовый HTTP-клиент с retry, timeout и JWT token propagation.

    Retry policy:
    - Retries on 5xx server errors, 408 (request timeout), 429 (rate limit)
    - Retries on transport errors (ConnectError, TimeoutException, NetworkError)
    - Does NOT retry on 4xx client errors (except 408/429) — won't help
    - Exponential backoff: 0.5s, 1s, 2s, 4s, 8s (capped)
    - Max retries configurable via ``max_retries`` constructor arg (default 3)
    - 401 → PermissionError (NOT retried, auth issue)
    """

    def __init__(
        self,
        base_url: str = _BASE_URL,
        token: str | None = None,
        max_retries: int = 3,
        timeout: float = 15.0,
        initial_backoff: float = _DEFAULT_INITIAL_BACKOFF,
        retry_overrides: dict[str, int] | None = None,
        jitter_ratio: float = 0.0,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._token = token
        self._max_retries = max_retries
        self._timeout = timeout
        self._initial_backoff = initial_backoff
        # TD-012: per-path retry overrides. Keys = exact path; values = max_retries.
        # Built-in defaults (health/ready → 0) are applied by _get_max_retries_for_path.
        self._retry_overrides: dict[str, int] = dict(retry_overrides or {})
        # TD-013: jitter — multiplicative randomisation of backoff, [1-r, 1+r].
        # Reduces thundering herd when many clients retry simultaneously.
        # 0.0 = deterministic (default, backward-compatible).
        self._jitter_ratio: float = max(0.0, min(1.0, jitter_ratio))

    def set_token(self, token: str | None) -> None:
        """Установить JWT token для последующих запросов."""
        self._token = token

    def _headers(self) -> dict[str, str]:
        """Собрать headers с auth token."""
        headers: dict[str, str] = {
            "Content-Type": "application/json",
            "Accept": "application/json",
        }
        if self._token:
            headers["Authorization"] = f"Bearer {self._token}"
        return headers

    def _get_max_retries_for_path(self, path: str) -> int:
        """TD-012: per-path retry policy.

        Returns the number of retries for a given URL path. Resolution order:
        1. ``self._retry_overrides[path]`` (constructor arg, exact path match).
        2. Built-in no-retry paths (``/health``, ``/ready``, health components).
        3. ``self._max_retries`` (default).

        Override this method in subclasses to add domain-specific policies
        (e.g. RAG long-running endpoints, admin write endpoints). Built-in
        defaults — это safe defaults, не safety constraint: явный
        ``retry_overrides`` всегда выигрывает.
        """
        if path in self._retry_overrides:
            return self._retry_overrides[path]
        # Health/liveness probes: fail fast, no retry.
        if path in ("/health", "/ready", "/api/v1/health/components"):
            return 0
        return self._max_retries

    def _sleep_backoff(self, attempt: int) -> None:
        """Sleep with exponential backoff (0.5, 1, 2, 4, 8s capped) + optional jitter.

        TD-013: when ``jitter_ratio > 0``, the backoff is multiplied by
        ``random.uniform(1 - jitter_ratio, 1 + jitter_ratio)``. This breaks
        synchronisation across many concurrent clients (thundering herd) by
        spreading retries across a time window. ``jitter_ratio=0.0`` →
        deterministic (default, backward-compatible).
        """
        backoff = min(
            self._initial_backoff * (2 ** attempt), _MAX_BACKOFF
        )
        if self._jitter_ratio > 0.0:
            # S311: not for crypto; this is for backoff spread only.
            factor = random.uniform(  # noqa: S311
                1.0 - self._jitter_ratio, 1.0 + self._jitter_ratio
            )
            backoff = max(0.0, backoff * factor)
        time.sleep(backoff)

    def get(self, path: str, **kwargs: Any) -> Any:
        return self._request("GET", path, **kwargs)

    def post(self, path: str, **kwargs: Any) -> Any:
        return self._request("POST", path, **kwargs)

    def put(self, path: str, **kwargs: Any) -> Any:
        return self._request("PUT", path, **kwargs)

    def patch(self, path: str, **kwargs: Any) -> Any:
        return self._request("PATCH", path, **kwargs)

    def delete(self, path: str, **kwargs: Any) -> Any:
        return self._request("DELETE", path, **kwargs)

    def _request(self, method: str, path: str, **kwargs: Any) -> Any:  # noqa: BLE001
        """Выполнить HTTP запрос с retry, exponential backoff и обработкой ошибок.

        Args:
            method: HTTP method (GET, POST, etc.).
            path: URL path (joined to base_url).
            **kwargs: forwarded to httpx.Client.request.

        Returns:
            Parsed JSON or text response.

        Raises:
            PermissionError: 401 Unauthorized (NOT retried).
            httpx.HTTPStatusError: 4xx (other than 401/408/429) — won't help.
            httpx.TransportError: after max_retries exhausted on 5xx/transport.
        """
        headers = {**self._headers(), **kwargs.pop("headers", {})}
        last_exc: Exception | None = None
        max_retries = self._get_max_retries_for_path(path)
        for attempt in range(max_retries + 1):
            try:
                with httpx.Client(timeout=self._timeout) as client:
                    response = client.request(
                        method, f"{self._base_url}{path}", headers=headers, **kwargs
                    )
                # 401 = auth issue, не retry (won't help)
                if response.status_code == 401:
                    msg = f"Unauthorized: {path}"
                    raise PermissionError(msg)
                # 5xx, 408, 429 = retryable
                if response.status_code in _RETRYABLE_STATUS_CODES:
                    if attempt < max_retries:
                        self._sleep_backoff(attempt)
                        continue
                    # Last attempt: raise
                    msg = f"Server error {response.status_code}: {path}"
                    raise httpx.HTTPStatusError(
                        msg, request=response.request, response=response
                    )
                # Other 4xx — не retry
                response.raise_for_status()
                ctype = response.headers.get("content-type", "")
                if ctype.startswith("application/json"):
                    return response.json()
                return response.text
            except (
                httpx.ConnectError,
                httpx.TimeoutException,
                httpx.NetworkError,
            ) as exc:
                last_exc = exc
                if attempt < max_retries:
                    self._sleep_backoff(attempt)
                    continue
                # Last attempt: re-raise
                raise
        # Should not reach here, but for type safety
        if last_exc is not None:
            raise last_exc
        msg = f"Request failed after {max_retries + 1} attempts: {path}"
        raise httpx.HTTPError(msg)


_client: BaseAPIClient | None = None


def get_base_client() -> BaseAPIClient:
    """Получить глобальный инстанс клиента."""
    global _client
    if _client is None:
        _client = BaseAPIClient()
    return _client
