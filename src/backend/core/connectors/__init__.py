"""Connector Catalog — unified metadata + lifecycle для external integrations (Wave 1 P0 #6).

Проблема (EP-R1):
    Каждый connector реализуется разнородно:
    - Нет единого metadata (config schema, auth model, health check).
    - validate_config() / test_connection() разбросаны по модулям.
    - UI не может показать "какие connectors доступны и как их настроить".

Решение:
    ``BaseConnector`` Protocol + ``ConnectorRegistry``:

    1. ``BaseConnector`` — общий интерфейс:
       - ``metadata()`` → ConnectorMetadata (name, version, auth_model, ...).
       - ``config_schema()`` → JSON Schema для config.
       - ``health_check()`` → ConnectorHealth (status, latency_ms, error).
       - ``test_connection()`` → bool (используется в UI wizard).
       - ``operations()`` → list операций (name, description, schema).

    2. ``ConnectorRegistry`` — singleton catalog:
       - ``register(connector)`` — register instance.
       - ``get(name)`` — lookup по name.
       - ``list_all()`` — все connectors с metadata.
       - ``search(filters)`` — фильтрация по category, auth_model, ...

Использование::

    from src.backend.core.connectors import (
        BaseConnector, ConnectorMetadata, ConnectorRegistry,
    )

    class MyHTTPConnector(BaseConnector):
        def metadata(self) -> ConnectorMetadata:
            return ConnectorMetadata(
                name="my-http",
                version="1.0.0",
                category="http",
                auth_model="api_key",
                description="My HTTP API connector",
            )

        # ...

    ConnectorRegistry.instance().register(MyHTTPConnector())
"""

from __future__ import annotations

from src.backend.core.connectors.base import (
    AuthModel,
    BaseConnector,
    ConnectorHealth,
    ConnectorMetadata,
    ConnectorStatus,
    OperationSchema,
)
from src.backend.core.connectors.registry import (
    ConnectorRegistry,
    get_connector_registry,
)

__all__ = (
    "AuthModel",
    "BaseConnector",
    "ConnectorHealth",
    "ConnectorMetadata",
    "ConnectorRegistry",
    "ConnectorStatus",
    "OperationSchema",
    "get_connector_registry",
)
