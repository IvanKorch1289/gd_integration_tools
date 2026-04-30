"""W24 — Контракт ImportGateway.

``ImportGateway`` — единый Gateway для импорта внешних спецификаций
(Postman v2.1 / OpenAPI 3.x / WSDL) во внутреннюю модель
:class:`ConnectorSpec`. Заменяет два legacy-стэка:
``src/tools/schema_importer/`` (sync, файловый) и ``src/dsl/importers/``
(async, in-memory).

Контракт минимален: ``import_spec(source)`` принимает raw content и
метаданные, возвращает нормализованный ``ConnectorSpec``. Конкретные
backend'ы живут в ``infrastructure/import_gateway/<kind>.py`` и
выбираются factory'ём ``infrastructure/import_gateway/factory.py``.

Composition root: ``services.integrations.import_service.ImportService``
оркестрирует import → idempotency check → register actions/sinks.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Protocol, runtime_checkable

__all__ = (
    "ImportSourceKind",
    "ImportSource",
    "ImportGateway",
)


class ImportSourceKind(str, Enum):
    """Тип импортируемой спецификации."""

    POSTMAN = "postman"
    OPENAPI = "openapi"
    WSDL = "wsdl"


@dataclass(slots=True)
class ImportSource:
    """Описание импортируемой спецификации.

    Args:
        kind: Тип спецификации (Postman / OpenAPI / WSDL).
        content: Сырое содержимое (JSON/YAML/XML текст).
        source_url: URL источника (для provenance/audit). Может быть
            ``None`` если spec пришёл локальным файлом / из Streamlit upload.
        prefix: Префикс для генерируемых route_id (default ``ext``).
        metadata: Произвольные метаданные импорта (uploaded_by, batch_id...).
    """

    kind: ImportSourceKind
    content: str | bytes
    source_url: str | None = None
    prefix: str = "ext"
    metadata: dict[str, str] = field(default_factory=dict)


@runtime_checkable
class ImportGateway(Protocol):
    """Контракт парсера-конвертера ``ImportSource → ConnectorSpec``.

    Stateless операция: backend парсит content, конвертирует в нормализованный
    ``ConnectorSpec`` и возвращает. Ни persist, ни регистрация actions/sinks
    в контракт не входят — это делает ``ImportService`` поверх Gateway.

    Реализации:

    * ``infrastructure.import_gateway.openapi.OpenAPIImportGateway``
    * ``infrastructure.import_gateway.postman.PostmanImportGateway``
    * ``infrastructure.import_gateway.wsdl.WsdlImportGateway``
    """

    kind: ImportSourceKind

    async def import_spec(self, source: ImportSource) -> "ConnectorSpec":
        """Распарсить spec и вернуть нормализованный ``ConnectorSpec``.

        Args:
            source: Описание импортируемой спецификации.

        Returns:
            ``ConnectorSpec`` — единая внутренняя модель коннектора.

        Raises:
            ImportError: Невалидный синтаксис spec'а.
            ValueError: Невалидная семантика (нет операций, unsupported version).
        """
        ...


# Прямой forward-ref на ConnectorSpec — модель в core/models/, импорт
# отложенный, чтобы избежать циклов при сериализации Protocol-сигнатур.
from src.core.models.connector_spec import ConnectorSpec  # noqa: E402,F401
