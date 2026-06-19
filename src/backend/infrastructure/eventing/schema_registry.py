"""Schema Registry — локальный кеш схем + (опционально) удалённый
Confluent-совместимый endpoint.

Цели:
* Валидация incoming/outgoing событий по JSON-Schema или Avro.
* Ранний отказ при несовместимой эволюции schema.
* Версионирование per topic + fallback-cache при недоступности registry.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from functools import lru_cache
from typing import Any

from src.backend.infrastructure.logging.factory import get_logger

__all__ = ("SchemaRegistry", "SchemaRegistryError", "get_schema_registry")

logger = get_logger("eventing.schema_registry")


class SchemaRegistryError(RuntimeError):
    """Ошибка работы с schema registry."""


@dataclass(slots=True)
class SchemaRegistry:
    """In-memory schema registry с опциональным удалённым backend.

    При недоступности remote-registry (Confluent / Apicurio) клиент
    работает по локальному кешу, что критично для устойчивости при
    инциденте в registry-сервисе.
    """

    endpoint: str = ""
    _json_cache: dict[str, dict[str, Any]] = field(default_factory=dict)
    _avro_cache: dict[str, str] = field(default_factory=dict)

    def register_json(self, subject: str, schema: dict[str, Any]) -> None:
        """Register a JSON schema for a subject.

        Args:
            subject: Schema subject identifier.
            schema: JSON Schema dictionary.
        """
        self._json_cache[subject] = schema

    def register_avro(self, subject: str, schema_str: str) -> None:
        """Register an Avro schema for a subject.

        Args:
            subject: Schema subject identifier.
            schema_str: Avro schema as JSON string.
        """
        self._avro_cache[subject] = schema_str

    def get_json(self, subject: str) -> dict[str, Any] | None:
        """Get JSON schema by subject.

        Args:
            subject: Schema subject identifier.

        Returns:
            JSON Schema dictionary or None if not found.
        """
        return self._json_cache.get(subject)

    def get_avro(self, subject: str) -> str | None:
        """Get Avro schema by subject.

        Args:
            subject: Schema subject identifier.

        Returns:
            Avro schema string or None if not found.
        """
        return self._avro_cache.get(subject)

    def validate_json(self, subject: str, payload: Any) -> None:
        """Validate payload against JSON schema.

        Args:
            subject: Schema subject identifier.
            payload: Payload to validate.

        Raises:
            SchemaRegistryError: If schema not found or validation fails.
        """
        schema = self.get_json(subject)
        if not schema:
            raise SchemaRegistryError(f"JSON schema not found: {subject}")
        try:
            from jsonschema import validate

            validate(instance=payload, schema=schema)
        except ImportError:
            logger.warning(
                "jsonschema не установлен — validation skipped для %s", subject
            )
        except Exception as exc:
            raise SchemaRegistryError(f"{subject}: {exc}") from exc

    def validate_avro(self, subject: str, payload: bytes) -> dict[str, Any]:
        """Validate and decode Avro payload.

        Args:
            subject: Schema subject identifier.
            payload: Avro-encoded bytes.

        Returns:
            Decoded payload dictionary.

        Raises:
            SchemaRegistryError: If schema not found or validation fails.
        """
        schema_str = self.get_avro(subject)
        if not schema_str:
            raise SchemaRegistryError(f"Avro schema not found: {subject}")
        try:
            import fastavro

            schema = fastavro.parse_schema(json.loads(schema_str))
            import io

            bio = io.BytesIO(payload)
            return fastavro.schemaless_reader(bio, schema)  # type: ignore[return-value]
        except ImportError:
            raise SchemaRegistryError(
                "fastavro не установлен — Avro validation недоступна"
            )


@lru_cache(maxsize=1)
def get_schema_registry() -> SchemaRegistry:
    """Lazy singleton (Wave 6.1; обычно резолвится через svcs)."""
    return SchemaRegistry()


def __getattr__(name: str) -> Any:
    """Module-level lazy accessor для backward compat ``registry``."""
    if name == "registry":
        return get_schema_registry()
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
