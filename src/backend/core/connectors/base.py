"""Base types для Connector Catalog (Wave 1 P0 #6)."""

from __future__ import annotations

import enum
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any


class AuthModel(str, enum.Enum):
    """Тип аутентификации connector'а."""

    NONE = "none"
    API_KEY = "api_key"
    BEARER = "bearer"
    BASIC = "basic"
    OAUTH2 = "oauth2"
    CERTIFICATE = "certificate"  # mTLS


class ConnectorStatus(str, enum.Enum):
    """Health status connector'а."""

    HEALTHY = "healthy"
    DEGRADED = "degraded"
    UNHEALTHY = "unhealthy"
    UNKNOWN = "unknown"


@dataclass(slots=True)
class ConnectorMetadata:
    """Метаданные connector'а для catalog."""

    name: str
    version: str
    category: str  # "http", "database", "messaging", "storage", ...
    auth_model: AuthModel
    description: str = ""
    owner: str = ""  # team or person
    tags: list[str] = field(default_factory=list)
    documentation_url: str = ""


@dataclass(slots=True)
class OperationSchema:
    """Описание операции connector'а."""

    name: str
    description: str = ""
    input_schema: dict[str, Any] = field(default_factory=dict)
    output_schema: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class ConnectorHealth:
    """Результат health check."""

    status: ConnectorStatus
    latency_ms: float | None = None
    error: str | None = None
    details: dict[str, Any] = field(default_factory=dict)


class BaseConnector(ABC):
    """Abstract base class для всех connector'ов."""

    @abstractmethod
    def metadata(self) -> ConnectorMetadata:
        """Метаданные connector'а (catalog entry)."""

    @abstractmethod
    def config_schema(self) -> dict[str, Any]:
        """JSON Schema для конфигурации connector'а.

        Returns:
            JSON Schema dict (используется для UI form generation
            и runtime validation).

        """

    @abstractmethod
    async def health_check(self) -> ConnectorHealth:
        """Проверить здоровье connector'а (lazy check, не кешируется)."""

    @abstractmethod
    async def test_connection(self, config: dict[str, Any]) -> bool:
        """Тестировать подключение с данным config (UI wizard).

        Returns:
            True если connection успешен.

        """

    @abstractmethod
    def operations(self) -> list[OperationSchema]:
        """Список операций connector'а (для docs/UI)."""
