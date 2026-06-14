"""SKB-Техно клиент для credit_pipeline (Sprint 7 Team T3).

Wave: ``[wave:s7/team-03-credit-1st-client]``. Каноническая точка
для credit-pipeline V11 (R-V15-13: per-service timeouts через
:class:`BaseExternalAPIClient` + :class:`OutboundHttpClient` (WAF)).

Под feature_flag.credit_pipeline_v2 (default-OFF):
* при ON используется этот клиент (через ``get_credit_skb_client``);
* при OFF callsites продолжают использовать legacy
  ``services.integrations.skb.APISKBService`` (миграция Sprint 8).

После flip default-ON legacy-клиент станет shim'ом → этот файл.
"""

from __future__ import annotations

from typing import Any
from uuid import UUID

from src.backend.core.config.settings import SKBAPISettings, settings
from src.backend.core.errors import ServiceError
from src.backend.core.services.base import BaseExternalAPIClient

__all__ = ("CreditSKBClient", "get_credit_skb_client")


class CreditSKBClient(BaseExternalAPIClient):
    """SKB-Техно клиент для credit-pipeline.

    Per-service timeouts наследуются от :class:`BaseExternalAPIClient`
    через ``SKBAPISettings`` (R-V15-13). Auth-схема — query-param
    ``api-key``, поэтому подкласс подмешивает его во все запросы
    через ``_request``.

    WAF-маршрутизация (R-V15-5): для production-окружения публичные
    запросы идут через настроенный ``waf_url`` (см. ``_waf_route``).
    """

    def __init__(self, skb_settings: SKBAPISettings) -> None:
        """Инициализация с настройками SKB.

        Args:
            skb_settings: Конфигурация (URL + api_key + timeouts).
        """
        super().__init__(settings=skb_settings, name="credit_skb")
        self._auth_params: dict[str, Any] = {"api-key": skb_settings.api_key}

    async def _request(
        self,
        method: str,
        url: str,
        *,
        params: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> Any:
        """Подмешивает ``api-key`` ко всем запросам SKB.

        Args:
            method: HTTP-метод.
            url: Полный URL endpoint'а.
            params: Дополнительные query-параметры (auth подмешивается).
            kwargs: Дополнительные аргументы передаются в transport.

        Returns:
            Ответ согласно ``response_type`` (json / bytes / text).
        """
        merged = {**self._auth_params, **(params or {})}
        return await super()._request(method, url, params=merged, **kwargs)

    def _waf_route(self) -> tuple[str | None, bool]:
        """Возвращает ``(waf_url, use_waf)`` для production-маршрутизации."""
        if (
            settings.app.environment == "production"
            and settings.http_base_settings.waf_url
        ):
            return settings.http_base_settings.waf_url, True
        return None, False

    async def get_request_kinds(self) -> dict[str, Any]:
        """Получает справочник видов запросов из SKB-Техно.

        Returns:
            Словарь с полем ``data.Data`` — список kinds.

        Raises:
            ServiceError: Если запрос не удался.
        """
        waf_url, use_waf = self._waf_route()
        url = waf_url or self._url("GET_KINDS")
        try:
            return await self._request("GET", url, use_waf=use_waf)
        except Exception as exc:
            raise ServiceError from exc

    async def create_request(self, data: dict[str, Any]) -> dict[str, Any]:
        """Создаёт запрос на получение данных по залогу в SKB-Техно.

        Args:
            data: Payload с параметрами запроса.

        Returns:
            Ответ с ``data.Id`` (UUID нового запроса).
        """
        try:
            return await self._request("POST", self._url("CREATE_REQUEST"), json=data)
        except Exception as exc:
            raise ServiceError from exc

    async def get_result(
        self, order_uuid: UUID, response_type_str: str | None = None
    ) -> Any | dict[str, Any]:
        """Получает результат по залогу (JSON или PDF).

        Args:
            order_uuid: UUID заказа в SKB-системе.
            response_type_str: ``JSON`` или ``PDF``.

        Returns:
            JSON-словарь или bytes PDF.
        """
        try:
            base = self._url("GET_RESULT").rstrip("/")
            url = f"{base}/{order_uuid}"
            response = await self._request(
                "GET",
                url,
                params={"Type": response_type_str},
                response_type="bytes" if response_type_str == "PDF" else "json",
                raise_for_status=False,
            )
            return response.get("data") if response_type_str == "PDF" else response
        except Exception as exc:
            raise ServiceError from exc


_credit_skb_client_instance: CreditSKBClient | None = None


def get_credit_skb_client() -> CreditSKBClient:
    """Возвращает singleton экземпляр :class:`CreditSKBClient`.

    Использует ``settings.skb_api_settings`` из глобальной конфигурации.
    """
    global _credit_skb_client_instance
    if _credit_skb_client_instance is None:
        _credit_skb_client_instance = CreditSKBClient(
            skb_settings=settings.skb_api_settings
        )
    return _credit_skb_client_instance
