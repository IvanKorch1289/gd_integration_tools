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

import logging
import time
from typing import Any
from urllib.parse import urljoin, urlparse

__all__ = ("BaseExternalAPIClient",)

logger = logging.getLogger("services.external_api")


class BaseExternalAPIClient:
    """Базовый класс для services, оборачивающих external HTTP API.

    Подклассы получают:
    - `self.client` — HttpClient singleton
    - `self.settings` — API settings
    - `self._url(endpoint_key)` — URL resolver из settings.endpoints
    - `self._headers()` — готовые headers (WAF / API-key / Authorization)
    - `self._request(method, url, **kwargs)` — обёртка с headers + timeout

    Settings могут содержать:
        base_url / prod_url: str
        api_key: str
        endpoints: dict[str, str]
        use_waf: bool (optional)
        connect_timeout, read_timeout: float (optional)

    Подклассы могут переопределить ``_auth_scheme`` (`"Bearer"` по умолчанию)
    для сервисов, использующих другие схемы (`"Token"`, и т. п.).
    """

    _auth_scheme: str = "Bearer"

    def __init__(
        self,
        *,
        settings: Any,
        name: str | None = None,
        outbound_http_client: Any | None = None,
    ) -> None:
        # Wave 6 finalize: HTTP-клиент резолвится через DI-провайдер
        # (см. ``core.di.providers.get_http_client_provider``) — это
        # снимает прямой импорт ``infrastructure.clients.transport.http``
        # из services-слоя.
        # Wave 1.5 (S1): при ``WAF_OUTBOUND_VIA_FACADE=True`` ходим через
        # ``OutboundHttpClient`` (Single Entry V15.1, R-V15-5). Phase-1 —
        # флаг по умолчанию False, прежнее поведение сохраняется.
        from src.backend.core.di.providers import get_http_client_provider

        self.settings = settings
        self._name = name or self.__class__.__name__
        self.client = get_http_client_provider()
        self._outbound_http_client = outbound_http_client
        self.base_url = (
            getattr(settings, "prod_url", None)
            or getattr(settings, "base_url", None)
            or ""
        )
        self.endpoints = getattr(settings, "endpoints", {}) or {}
        self._logger = logging.getLogger(f"services.{self._name.lower()}")

    def _resolve_outbound_facade(self) -> Any | None:
        """Lazy-резолв ``OutboundHttpClient`` из svcs (если включён feature-flag)."""
        if self._outbound_http_client is not None:
            return self._outbound_http_client
        try:
            from src.backend.core.config.waf import waf_settings
        except Exception:  # noqa: BLE001
            return None
        if not getattr(waf_settings, "outbound_via_facade", False):
            return None
        try:
            from src.backend.core.net.outbound_http import OutboundHttpClient
            from src.backend.core.svcs_registry import get_service, has_service
        except Exception:  # noqa: BLE001
            return None
        if not has_service(OutboundHttpClient):
            return None
        try:
            return get_service(OutboundHttpClient)
        except Exception:  # noqa: BLE001
            return None

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
        from src.backend.core.config.settings import settings as app_settings

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
                headers["Authorization"] = f"{self._auth_scheme} {api_key}"

        if extra:
            headers.update(extra)
        return headers

    def _timeouts(
        self, *, host: str | None = None, endpoint: str | None = None
    ) -> dict[str, float]:
        """Возвращает connect/read/total таймауты из settings.

        Если задан ``host`` + ``endpoint`` и
        :class:`AdaptiveTimeoutPolicy` уже накопила достаточно сэмплов
        (см. ``_MIN_SAMPLES_FOR_P99``) — total_timeout заменяется
        на рекомендацию policy. Иначе остаётся hardcoded
        ``connect + read`` (backwards compatible).
        """
        connect = float(getattr(self.settings, "connect_timeout", 10))
        read = float(getattr(self.settings, "read_timeout", 30))
        total = connect + read
        if host and endpoint:
            try:
                from src.backend.core.resilience.adaptive_timeout import (
                    get_adaptive_timeout_policy,
                )

                total = get_adaptive_timeout_policy().get_timeout(
                    host, endpoint, default_seconds=total
                )
            except Exception as exc:  # noqa: BLE001
                logger.debug(
                    "BaseExternalAPIClient: adaptive timeout policy lookup failed: %s",
                    exc,
                )
        return {
            "connect_timeout": connect,
            "read_timeout": read,
            "total_timeout": total,
        }

    def _record_endpoint_latency(
        self, host: str, endpoint: str, latency_ms: float
    ) -> None:
        """Best-effort вызов :meth:`AdaptiveTimeoutPolicy.record_latency`.

        Исключения подавляются — статистика не должна мешать запросу.
        """
        try:
            from src.backend.core.resilience.adaptive_timeout import (
                get_adaptive_timeout_policy,
            )

            get_adaptive_timeout_policy().record_latency(host, endpoint, latency_ms)
        except Exception as exc:  # noqa: BLE001
            logger.debug("BaseExternalAPIClient: record latency failed: %s", exc)

    async def _request(
        self,
        method: str,
        url: str,
        *,
        params: dict[str, Any] | None = None,
        json: Any = None,
        headers: dict[str, str] | None = None,
        use_waf: bool | None = None,
        response_type: str | None = None,
        raise_for_status: bool | None = None,
        **extra_kwargs: Any,
    ) -> Any:
        """Единый request wrapper с unified headers + timeout + logging.

        ``response_type`` / ``raise_for_status`` пробрасываются в
        ``HttpClient.make_request`` только если заданы — иначе используются
        дефолты HttpClient. Доп. kwargs прозрачно передаются дальше.
        """
        full_headers = self._headers(extra=headers, use_waf=use_waf)
        # AdaptiveTimeoutPolicy: host/endpoint извлекаются из URL и
        # передаются в _timeouts(); они же используются для записи
        # latency в finally-блоке ниже.
        parsed = urlparse(url)
        host = parsed.hostname or ""
        endpoint = parsed.path or ""
        kwargs: dict[str, Any] = {
            **self._timeouts(host=host, endpoint=endpoint),
            **extra_kwargs,
        }
        if response_type is not None:
            kwargs["response_type"] = response_type
        if raise_for_status is not None:
            kwargs["raise_for_status"] = raise_for_status

        facade = self._resolve_outbound_facade()
        start_monotonic = time.monotonic()
        try:
            if facade is not None:
                try:
                    response = await facade.request(
                        method, url, params=params, json=json, headers=full_headers
                    )
                except Exception as exc:
                    self._logger.error(
                        "%s outbound facade failed: %s %s — %s",
                        self._name,
                        method,
                        url,
                        exc,
                    )
                    raise
                if response_type == "text":
                    return response.text
                if response_type == "bytes":
                    return response.content
                try:
                    return response.json()
                except ValueError:
                    return response.text

            try:
                return await self.client.make_request(
                    method=method,
                    url=url,
                    params=params,
                    json=json,
                    headers=full_headers,
                    **kwargs,
                )
            except Exception as exc:
                self._logger.error(
                    "%s request failed: %s %s — %s", self._name, method, url, exc
                )
                raise
        finally:
            if host and endpoint:
                latency_ms = (time.monotonic() - start_monotonic) * 1000.0
                self._record_endpoint_latency(host, endpoint, latency_ms)
