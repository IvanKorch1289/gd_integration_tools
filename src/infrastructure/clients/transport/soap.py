"""SOAP-клиент с поддержкой retry и circuit breaker.

Обёртка над ``zeep`` для вызова внешних WSDL-сервисов.
Поддерживает async-вызовы через ``asyncio.to_thread``.
"""

import asyncio
import logging
from typing import Any

from zeep import Client, Settings
from zeep.exceptions import Error as ZeepError
from zeep.exceptions import Fault as ZeepFault

from app.core.errors import ServiceError

__all__ = ("SoapClient", "get_soap_client")

logger = logging.getLogger(__name__)


class SoapClient:
    """Асинхронный SOAP-клиент.

    Загружает WSDL при инициализации и предоставляет
    метод ``call()`` для вызова операций сервиса.

    Attrs:
        wsdl_url: URL WSDL-документа.
        timeout: Таймаут операции в секундах.
        strict: Строгий режим валидации XML.
    """

    def __init__(
        self,
        wsdl_url: str,
        *,
        timeout: int = 30,
        strict: bool = False,
    ) -> None:
        self.wsdl_url = wsdl_url
        self.timeout = timeout
        self._settings = Settings(
            strict=strict,
            xml_huge_tree=True,
        )
        self._client: Client | None = None

    def _ensure_client(self) -> Client:
        """Ленивая инициализация zeep-клиента."""
        if self._client is None:
            self._client = Client(
                wsdl=self.wsdl_url,
                settings=self._settings,
            )
            logger.info(
                "SOAP-клиент инициализирован: %s", self.wsdl_url
            )
        return self._client

    def _call_sync(
        self,
        operation: str,
        **kwargs: Any,
    ) -> Any:
        """Синхронный вызов SOAP-операции.

        Args:
            operation: Имя операции (метод WSDL-сервиса).
            **kwargs: Параметры вызова.

        Returns:
            Результат вызова (zeep сериализует в dict/list).
        """
        client = self._ensure_client()
        service = client.service
        method = getattr(service, operation)
        return method(**kwargs)

    async def call(
        self,
        operation: str,
        **kwargs: Any,
    ) -> Any:
        """Асинхронный вызов SOAP-операции.

        Args:
            operation: Имя операции (метод WSDL-сервиса).
            **kwargs: Параметры вызова.

        Returns:
            Результат вызова.

        Raises:
            ServiceError: При ошибке SOAP-вызова.
        """
        try:
            result = await asyncio.to_thread(
                self._call_sync, operation, **kwargs
            )
            logger.debug(
                "SOAP вызов %s.%s выполнен",
                self.wsdl_url,
                operation,
            )
            return result
        except ZeepFault as exc:
            logger.error(
                "SOAP Fault при вызове %s: %s",
                operation,
                exc.message,
            )
            raise ServiceError(
                detail=f"SOAP Fault: {exc.message}"
            ) from exc
        except ZeepError as exc:
            logger.error(
                "SOAP ошибка при вызове %s: %s",
                operation,
                exc,
            )
            raise ServiceError(
                detail=f"SOAP Error: {exc}"
            ) from exc

    def list_operations(self) -> list[str]:
        """Возвращает список доступных SOAP-операций.

        Returns:
            Список имён операций из WSDL.
        """
        client = self._ensure_client()
        operations: list[str] = []
        for service in client.wsdl.services.values():
            for port in service.ports.values():
                operations.extend(
                    op.name for op in port.binding._operations.values()
                )
        return sorted(set(operations))

    async def close(self) -> None:
        """Закрывает транспорт zeep-клиента."""
        if self._client and self._client.transport:
            self._client.transport.session.close()
            self._client = None


def get_soap_client(
    wsdl_url: str,
    *,
    timeout: int = 30,
) -> SoapClient:
    """Фабрика для создания SOAP-клиента.

    Args:
        wsdl_url: URL WSDL-документа.
        timeout: Таймаут в секундах.

    Returns:
        Экземпляр ``SoapClient``.
    """
    return SoapClient(wsdl_url=wsdl_url, timeout=timeout)
