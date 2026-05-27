"""Универсальный API клиент для произвольных запросов."""

from __future__ import annotations

import json
from typing import Any

from src.frontend.streamlit_app.api_clients.base import BaseAPIClient

__all__ = ("APICallerClient",)


class APICallerClient(BaseAPIClient):
    """Универсальный клиент для ручных API-вызовов из UI."""

    def call(
        self,
        method: str,
        path: str,
        headers: dict[str, str] | None = None,
        body: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Выполнить произвольный API-запрос.

        Args:
            method: HTTP метод (GET/POST/PUT/PATCH/DELETE).
            path:URL path.
            headers: Опциональные headers.
            body: Опциональный JSON body.

        Returns:
            dict с ключами status_code, body, elapsed_ms.
        """
        import time

        started = time.perf_counter()
        try:
            kwargs: dict[str, Any] = {}
            if headers:
                kwargs["headers"] = headers
            if body is not None and method != "GET":
                kwargs["json"] = body

            resp = self._request(method, path, **kwargs)
            elapsed_ms = (time.perf_counter() - started) * 1000

            if isinstance(resp, str):
                body_out: Any = {"raw": resp[:10_000]}
            else:
                body_out = resp

            return {
                "status_code": 200,
                "body": body_out,
                "elapsed_ms": round(elapsed_ms),
                "ok": True,
            }
        except Exception as exc:  # noqa: BLE001
            elapsed_ms = (time.perf_counter() - started) * 1000
            return {
                "status_code": 0,
                "body": {"error": str(exc)},
                "elapsed_ms": round(elapsed_ms),
                "ok": False,
            }
