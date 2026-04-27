"""BaseExternalAPIClient — общая база для сервисов external API.

Устраняет дубликаты в SKB/DaData/WebAutomation (3× boilerplate):
- WAF routing (production vs dev)
- API key / Bearer auth headers
- Timeout config (connect/read/total)
- Retry policy через shared HttpClient

Usage::

    class MyExternalService(BaseExternalAPIClient):
        def __init__(self, settings: MyAPISettings):
            super().__init__(settings=settings)

        async def get_items(self) -> dict:
            return await self._request("GET", self._url("list_items"))
"""

from __future__ import annotations

import logging
from typing import Any
from urllib.parse import urljoin

__all__ = ("BaseExternalAPIClient",)

logger = logging.getLogger("services.external_api")


class BaseExternalAPIClient:
    """Базовый класс для services, оборачивающих external HTTP API.

    Подклассы получают:
    - `self.client` — HttpClient singleton
    - `self.settings` — API settings
    - `self._url(endpoint_key)` — URL resolver из settings.endpoints
    - `self._headers()` — готовые headers (WAF/API-key/Bearer)
    - `self._request(method, url, **kwargs)` — обёртка с headers + timeout

    Settings могут содержать:
        base_url / prod_url: str
        api_key: str
        endpoints: dict[str, str]
        use_waf: bool (optional)
        connect_timeout, read_timeout: float (optional)
    """

    def __init__(self, *, settings: Any, name: str | None = None) -> None:
        from src.infrastructure.clients.transport.http import get_http_client_dependency

        self.settings = settings
        self._name = name or self.__class__.__name__
        self.client = get_http_client_dependency()
        self.base_url = (
            getattr(settings, "prod_url", None)
            or getattr(settings, "base_url", None)
            or ""
        )
        self.endpoints = getattr(settings, "endpoints", {}) or {}
        self._logger = logging.getLogger(f"services.{self._name.lower()}")

    def _url(self, endpoint_key: str) -> str:
        """Формирует полный URL из endpoints dict по ключу."""
        endpoint = self.endpoints.get(endpoint_key, "")
        if not endpoint:
            self._logger.warning("Endpoint '%s' not found in config", endpoint_key)
        return urljoin(self.base_url, endpoint)

    def _headers(
        self, *, extra: dict[str, str] | None = None, use_waf: bool | None = None
    ) -> dict[str, str]:
        """Формирует headers с учётом WAF routing и auth.

        WAF режим (production): заменяет Authorization/endpoint на WAF-прокси.
        Dev режим: прямая передача API key.
        """
        from src.core.config.settings import settings as app_settings

        headers: dict[str, str] = {"Content-Type": "application/json"}

        waf_active = use_waf
        if waf_active is None:
            waf_active = (
                app_settings.app.environment == "production"
                and bool(getattr(app_settings.http_base_settings, "waf_url", None))
                and getattr(self.settings, "use_waf", False)
            )

        if waf_active:
            waf_headers = getattr(
                app_settings.http_base_settings, "waf_route_header", {}
            )
            if isinstance(waf_headers, dict):
                headers.update(waf_headers)
        else:
            api_key = getattr(self.settings, "api_key", None)
            if api_key:
                if hasattr(api_key, "get_secret_value"):
                    api_key = api_key.get_secret_value()
                headers["Authorization"] = f"Bearer {api_key}"

        if extra:
            headers.update(extra)
        return headers

    def _timeouts(self) -> dict[str, float]:
        """Возвращает connect/read/total таймауты из settings."""
        connect = float(getattr(self.settings, "connect_timeout", 10))
        read = float(getattr(self.settings, "read_timeout", 30))
        return {
            "connect_timeout": connect,
            "read_timeout": read,
            "total_timeout": connect + read,
        }

    async def _request(
        self,
        method: str,
        url: str,
        *,
        params: dict[str, Any] | None = None,
        json: Any = None,
        headers: dict[str, str] | None = None,
        use_waf: bool | None = None,
    ) -> dict[str, Any]:
        """Единый request wrapper с unified headers + timeout + logging."""
        full_headers = self._headers(extra=headers, use_waf=use_waf)
        timeouts = self._timeouts()

        try:
            return await self.client.make_request(
                method=method,
                url=url,
                params=params,
                json=json,
                headers=full_headers,
                **timeouts,
            )
        except Exception as exc:
            self._logger.error(
                "%s request failed: %s %s — %s", self._name, method, url, exc
            )
            raise
