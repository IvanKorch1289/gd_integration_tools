"""Адаптер SOAP-клиента под Protocol :class:`app.core.protocols.SoapClient`.

Тонкая обёртка вокруг ``zeep`` (async-transport). Загружает WSDL один раз
и кэширует — повторные вызовы быстрые. Реализует только два метода,
запрошенных Protocol'ом: ``call(method, **params)`` и ``list_methods()``.
"""

from __future__ import annotations

import logging
from typing import Any

__all__ = ("ZeepSoapAdapter",)

logger = logging.getLogger(__name__)


class ZeepSoapAdapter:
    """SOAP-клиент на базе ``zeep.AsyncClient``.

    Args:
        wsdl_url: URL к WSDL-документу.
        auth: Опциональный HTTP Basic auth кортеж ``(user, password)``.
    """

    def __init__(self, wsdl_url: str, *, auth: tuple[str, str] | None = None) -> None:
        self._wsdl_url = wsdl_url
        self._auth = auth
        self._client: Any = None  # lazy-init при первом вызове

    async def _ensure_client(self) -> Any:
        """Lazy-инициализация zeep-клиента: WSDL загружается один раз."""
        if self._client is not None:
            return self._client
        try:
            from zeep import AsyncClient
            from zeep.transports import AsyncTransport
        except ImportError as exc:
            raise RuntimeError("zeep не установлен: pip install zeep") from exc

        import httpx

        session = httpx.AsyncClient(auth=self._auth if self._auth else None, timeout=30)
        transport = AsyncTransport(client=session)
        self._client = AsyncClient(wsdl=self._wsdl_url, transport=transport)
        return self._client

    async def call(self, method: str, **params: Any) -> Any:
        """Вызывает SOAP-метод. Exception'ы zeep пробрасываются как есть."""
        client = await self._ensure_client()
        fn = getattr(client.service, method, None)
        if fn is None:
            raise AttributeError(f"SOAP-метод '{method}' не найден в WSDL")
        return await fn(**params)

    def list_methods(self) -> list[str]:
        """Список доступных операций (из уже загруженного WSDL)."""
        if self._client is None:
            logger.warning("WSDL ещё не загружен — вызовите call() хотя бы один раз")
            return []
        try:
            # zeep: итератор по операциям первого сервиса и порта
            service = next(iter(self._client.wsdl.services.values()))
            port = next(iter(service.ports.values()))
            return sorted(port.binding._operations.keys())  # noqa: SLF001
        except Exception as exc:  # noqa: BLE001
            logger.debug("Не удалось извлечь список методов: %s", exc)
            return []
