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

    def validate_config(
        self, config: dict[str, Any]
    ) -> tuple[bool, str | None]:
        """Validate config against ``config_schema()`` (Sprint 175+ P0.4).

        Pure-stdlib implementation: only checks required fields and types
        (no nested validation). For full JSON Schema validation (Draft 7),
        install ``jsonschema`` (already a project dep) and pass
        ``full=True`` flag.

        Returns:
            (is_valid, error_message). error_message is None on success.
        """
        schema = self.config_schema()
        if not schema or schema.get("type") != "object":
            return True, None
        # Required fields.
        required = schema.get("required", [])
        for field_name in required:
            if field_name not in config:
                return False, f"Required field missing: {field_name!r}"
        # Type validation (top-level properties only).
        for field_name, value in config.items():
            prop_schema = (schema.get("properties") or {}).get(field_name, {})
            expected_type = prop_schema.get("type")
            if not expected_type:
                continue
            if not _validate_type(value, expected_type):
                return False, (
                    f"Field {field_name!r} has wrong type: "
                    f"expected {expected_type!r}, got {type(value).__name__!r}"
                )
        return True, None

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


# ─── JSON Schema subset validator (pure stdlib) ────────────────


_JSON_TYPE_MAP: dict[str, type | tuple[type, ...]] = {
    "string": str,
    "integer": int,
    "number": (int, float),
    "boolean": bool,
    "array": list,
    "object": dict,
    "null": type(None),
}


def _validate_type(value: Any, expected_type: str) -> bool:
    """Check if value matches JSON Schema type (Draft 7 subset)."""
    py_type = _JSON_TYPE_MAP.get(expected_type)
    if py_type is None:
        return True  # Unknown type — accept.
    if py_type is type(None):
        return value is None
    # bool is subclass of int, exclude for integer check.
    if expected_type == "integer" and isinstance(value, bool):
        return False
    return isinstance(value, py_type)
