"""Async HTTP-клиент для windows-worker Desktop RPA endpoints.

Wave: ``[wave:s8/k3-rpa-windows-desktop]``. Обращается к sidecar'у
(``windows_worker.handlers.desktop_rpa_handler``) по REST для выполнения
``click`` / ``type`` / ``screenshot`` действий через pywinauto.

Используется из DSL-шага ``.desktop_rpa(app, action, params)``.
"""

from __future__ import annotations

import logging
from typing import Any

import httpx

__all__ = ("DesktopRpaClient", "DesktopRpaError")

_logger = logging.getLogger(__name__)

# Все поддерживаемые действия и соответствующие endpoint'ы worker'а.
SUPPORTED_ACTIONS: dict[str, str] = {
    "click": "/rpa/click",
    "type": "/rpa/type",
    "screenshot": "/rpa/screenshot",
}


class DesktopRpaError(RuntimeError):
    """Ошибка вызова desktop-RPA sidecar'а."""


class DesktopRpaClient:
    """Тонкий async-клиент к windows-worker Desktop RPA.

    Args:
        base_url: URL sidecar'а (``http://windows-worker:9001``).
        api_key: Опц. API-key для аутентификации (header
            ``X-API-Key``).
        timeout: Connect+read timeout HTTP-запроса.
    """

    def __init__(
        self,
        base_url: str,
        *,
        api_key: str | None = None,
        timeout: float = 30.0,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._api_key = api_key
        self._timeout = timeout

    async def execute(
        self, action: str, params: dict[str, Any]
    ) -> dict[str, Any]:
        """Выполняет ``action`` (click/type/screenshot) на windows-worker.

        Args:
            action: Один из ``SUPPORTED_ACTIONS``.
            params: Тело запроса (см. Pydantic-модели handler'а).

        Returns:
            JSON-ответ worker'а.

        Raises:
            DesktopRpaError: Невалидный action / HTTP-ошибка / sidecar 503.
        """
        if action not in SUPPORTED_ACTIONS:
            raise DesktopRpaError(
                f"Unsupported action {action!r}; "
                f"поддерживаются: {sorted(SUPPORTED_ACTIONS)}"
            )

        url = f"{self._base_url}{SUPPORTED_ACTIONS[action]}"
        headers: dict[str, str] = {}
        if self._api_key:
            headers["X-API-Key"] = self._api_key

        async with httpx.AsyncClient(timeout=self._timeout) as http:
            try:
                response = await http.post(url, json=params, headers=headers)
            except httpx.HTTPError as exc:
                raise DesktopRpaError(
                    f"transport error к {url}: {exc}"
                ) from exc

        if response.status_code == 503:
            raise DesktopRpaError(
                "windows-worker недоступен (503): pywinauto не установлен "
                "или sidecar не на Windows."
            )
        if response.status_code >= 400:
            raise DesktopRpaError(
                f"{action} failed ({response.status_code}): "
                f"{response.text[:200]}"
            )
        return response.json()
