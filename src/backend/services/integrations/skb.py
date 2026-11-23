"""СКБ-Техно API сервис — поверх ``BaseExternalAPIClient``.

Auth-схема СКБ — query-параметр ``api-key``, поэтому подкласс подмешивает его
во все запросы через override ``_request``.

Cycle-35 B2: чистая логика WAF-маршрутизации вынесена в
``extensions.skb.services.waf_route.resolve_waf_route``. Старый
shim-символ ``resolve_waf_route`` оставлен здесь для backward-compat
с ``DeprecationWarning`` (удалить в Sprint 37+).

ADR-0457: резолвер берётся из core-реестра ресурсов расширений — статической
зависимости ``src/ → extensions`` не остаётся (``tools/check_layers.py``).
Резолв ленивый (в момент вызова), поэтому импорт модуля не тянет расширения.
"""

import warnings
from typing import Any
from uuid import UUID

from src.backend.core.config.settings import SKBAPISettings, settings
from src.backend.core.enums.skb import ResponseTypeChoices, response_type_value
from src.backend.core.errors import ServiceError
from src.backend.core.extension_registry import get_extension_resource
from src.backend.services.core.base_external_api import BaseExternalAPIClient

__all__ = ("APISKBService", "get_skb_service", "resolve_waf_route")

#: Значение типа ответа, при котором возвращается документ (PDF).
PDF_RESPONSE_TYPE = ResponseTypeChoices.pdf.value


class APISKBService(BaseExternalAPIClient):
    """Сервис для взаимодействия с API СКБ-Техно."""

    def __init__(self, skb_settings: SKBAPISettings) -> None:
        super().__init__(settings=skb_settings, name="skb")
        self._auth_params: dict[str, Any] = {"api-key": skb_settings.api_key}

    async def _request(
        self,
        method: str,
        url: str,
        *,
        params: dict[str, Any] | None = None,
        **kwargs: Any,
    ) -> Any:
        """Подмешивает ``api-key`` ко всем запросам СКБ."""
        merged = {**self._auth_params, **(params or {})}
        return await super()._request(method, url, params=merged, **kwargs)

    def _waf_route(self) -> tuple[str | None, bool]:
        """Возвращает (waf_url, use_waf) для production-маршрутизации.

        Используется только в эндпоинте справочника видов запросов.
        Cycle-35 B2: чистая логика делегирована
        ``extensions.skb.services.waf_route.resolve_waf_route``.
        """
        resolver = get_extension_resource("skb", "service", "resolve_waf_route")
        return resolver(settings.app.environment, settings.http_base_settings.waf_url)

    async def get_request_kinds(self) -> dict[str, Any]:
        """Получить справочник видов запросов из СКБ-Техно."""
        waf_url, use_waf = self._waf_route()
        url = waf_url or self._url("GET_KINDS")
        try:
            return await self._request("GET", url, use_waf=use_waf)
        except Exception as exc:
            raise ServiceError from exc

    async def add_request(self, data: dict[str, Any]) -> dict[str, Any]:
        """Создать запрос на получение данных по залогу в СКБ-Техно."""
        try:
            return await self._request("POST", self._url("CREATE_REQUEST"), json=data)
        except Exception as exc:
            raise ServiceError from exc

    async def get_response_by_order(
        self, order_uuid: UUID, response_type_str: str | None = None
    ) -> Any | dict[str, Any]:
        """Получить результат по залогу из СКБ-Техно.

        Args:
            order_uuid: UUID заказа в СКБ-системе.
            response_type_str: Тип ответа (``"JSON"`` / ``"PDF"``). Приходит
                как enum-член :class:`ResponseTypeChoices` (query-параметр
                FastAPI) либо строкой — значение нормализуется через
                :func:`response_type_value`, иначе ветка «PDF» не срабатывала
                и клиент получал JSON вместо документа.

        Returns:
            JSON-ответ либо bytes документа.
        """
        response_type = response_type_value(response_type_str)
        try:
            base = self._url("GET_RESULT").rstrip("/")
            url = f"{base}/{order_uuid}"
            response = await self._request(
                "GET",
                url,
                params={"Type": response_type},
                response_type="bytes" if response_type == PDF_RESPONSE_TYPE else "json",
                raise_for_status=False,
            )
            return (
                response.get("data") if response_type == PDF_RESPONSE_TYPE else response
            )
        except Exception as exc:
            raise ServiceError from exc

    async def get_orders_list(
        self, take: int | None = None, skip: int | None = None
    ) -> dict[str, Any]:
        """Получить список заказов документов по залогу из СКБ-Техно."""
        params: dict[str, Any] = {}
        if take is not None:
            params["take"] = take
        if skip is not None:
            params["skip"] = skip
        try:
            return await self._request(
                "GET",
                self._url("GET_ORDER_LIST"),
                params=params or None,
                raise_for_status=False,
            )
        except Exception as exc:
            raise ServiceError from exc

    async def get_objects_by_address(
        self, query: str, comment: str | None = None
    ) -> dict[str, Any]:
        """Проверка-поиск объектов недвижимости по адресу."""
        params: dict[str, Any] = {"query": query}
        if comment is not None:
            params["comment"] = comment
        try:
            return await self._request(
                "POST",
                self._url("CHECK_ADDRESS"),
                params=params,
                raise_for_status=False,
            )
        except Exception as exc:
            raise ServiceError from exc


_skb_service_instance: APISKBService | None = None


def get_skb_service() -> APISKBService:
    """Фабрика: APISKBService (банковский API)."""
    global _skb_service_instance
    if _skb_service_instance is None:
        _skb_service_instance = APISKBService(skb_settings=settings.skb_api)
    return _skb_service_instance


# Cycle-35 B2: backward-compat shim для ранее приватного WAF-решателя.
# Функция была приватным методом ``APISKBService._waf_route``, но в тестах и
# DSL-роутах иногда использовалась как ``from skb import resolve_waf_route``.
# Оставляем модульный символ с DeprecationWarning на одну мажорную версию.
def resolve_waf_route(
    environment: str | None, waf_url: str | None
) -> tuple[str | None, bool]:
    """DEPRECATED: используйте ``extensions.skb.services.waf_route.resolve_waf_route``."""
    warnings.warn(
        "resolve_waf_route из src.backend.services.integrations.skb устарел; "
        "импортируйте из extensions.skb.services.waf_route.",
        DeprecationWarning,
        stacklevel=2,
    )
    resolver = get_extension_resource("skb", "service", "resolve_waf_route")
    return resolver(environment, waf_url)
