"""Базовый HTTP-клиент с retry, timeout и JWT token propagation."""

from __future__ import annotations

import os
from typing import Any

import httpx

__all__ = ("BaseAPIClient", "get_base_client")

_BASE_URL = os.environ.get("API_BASE_URL", "http://localhost:8000")


class BaseAPIClient:
    """Базовый HTTP-клиент с retry, timeout и JWT token propagation."""

    def __init__(
        self,
        base_url: str = _BASE_URL,
        token: str | None = None,
        max_retries: int = 3,
        timeout: float = 15.0,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._token = token
        self._max_retries = max_retries
        self._timeout = timeout

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

    def _request(
        self, method: str, path: str, **kwargs: Any
    ) -> Any:  # noqa: BLE001
        """Выполнить HTTP запрос с retry и обработкой ошибок."""
        headers = {**self._headers(), **kwargs.pop("headers", {})}
        with httpx.Client(timeout=self._timeout) as client:
            response = client.request(
                method,
                f"{self._base_url}{path}",
                headers=headers,
                **kwargs,
            )
            if response.status_code == 401:
                msg = f"Unauthorized: {path}"
                raise PermissionError(msg)
            if response.status_code >= 500:
                msg = f"Server error {response.status_code}: {path}"
                raise httpx.HTTPStatusError(
                    msg, request=response.request, response=response
                )
            response.raise_for_status()
            ctype = response.headers.get("content-type", "")
            if ctype.startswith("application/json"):
                return response.json()
            return response.text

    def get(self, path: str, **kwargs: Any) -> Any:
        return self._request("GET", path, **kwargs)

    def post(self, path: str, **kwargs: Any) -> Any:
        return self._request("POST", path, **kwargs)

    def put(self, path: str, **kwargs: Any) -> Any:
        return self._request("PUT", path, **kwargs)

    def delete(self, path: str, **kwargs: Any) -> Any:
        return self._request("DELETE", path, **kwargs)

    def patch(self, path: str, **kwargs: Any) -> Any:
        return self._request("PATCH", path, **kwargs)


_client: BaseAPIClient | None = None


def get_base_client() -> BaseAPIClient:
    """Получить глобальный инстанс клиента."""
    global _client
    if _client is None:
        _client = BaseAPIClient()
    return _client
