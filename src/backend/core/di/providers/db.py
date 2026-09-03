"""DB domain providers — OLAP, document, file, connector registry, CDC, S3.

T-P1.2c split: извлечено из monolithic ``providers.py`` (S38 P1 epic).
Domain scope: 15 funcs (8 get + 7 set), 0 private helpers.

Singleton cache ``_overrides`` is per-domain (NOT shared).
"""

from __future__ import annotations

from typing import Any

from src.backend.core.di.module_registry import resolve_module

_overrides: dict[str, Any] = {}


# ─────────────── ClickHouse client (OLAP) ───────────────


def get_clickhouse_client_provider() -> Any:
    """Возвращает singleton ``ClickHouseClient`` (см. ``ClickHouseClientProtocol``)."""
    if "clickhouse_client" in _overrides:
        return _overrides["clickhouse_client"]
    module = resolve_module("clients.storage.clickhouse")
    return module.get_clickhouse_client()


def set_clickhouse_client_provider(client: Any) -> None:
    """Установить override для ``clickhouse_client`` provider (test-инжекция)."""
    _overrides["clickhouse_client"] = client


# ─────────────── MongoDB client (document store) ───────────────


def get_mongo_client_provider() -> Any:
    """Возвращает фабрику ``MongoDBClient`` (см. ``MongoClientProtocol``)."""
    if "mongo_client" in _overrides:
        return _overrides["mongo_client"]
    module = resolve_module("clients.storage.mongodb")
    return module.get_mongo_client


def set_mongo_client_provider(factory: Any) -> None:
    """Установить override для ``mongo_client`` provider (test-инжекция)."""
    _overrides["mongo_client"] = factory


# ─────────────── File repository ───────────────


def get_file_repo_provider() -> Any:
    """Возвращает фабрику ``FileRepository`` (см. ``FileRepositoryProtocol``)."""
    if "file_repo" in _overrides:
        return _overrides["file_repo"]
    module = resolve_module("repos.files")
    return module.get_file_repo()


def set_file_repo_provider(repo: Any) -> None:
    """Установить override для ``file_repo`` provider (test-инжекция)."""
    _overrides["file_repo"] = repo


# ─────────────── Connector configs (Mongo store) ───────────────


def get_connector_config_store_provider() -> Any:
    """Возвращает singleton ``MongoConnectorConfigStore``."""
    if "connector_config_store" in _overrides:
        return _overrides["connector_config_store"]
    module = resolve_module("repos.connector_configs")
    return module.get_connector_config_store()


def set_connector_config_store_provider(store: Any) -> None:
    """Установить override для ``connector_config_store`` provider (test-инжекция)."""
    _overrides["connector_config_store"] = store


# ─────────────── Connector registry ───────────────


def get_connector_registry_provider() -> Any:
    """Возвращает singleton ``ConnectorRegistry`` через ``ConnectorRegistry.instance()``."""
    if "connector_registry" in _overrides:
        return _overrides["connector_registry"]
    module = resolve_module("registry")
    return module.ConnectorRegistry.instance()


def set_connector_registry_provider(registry: Any) -> None:
    """Установить override для ``connector_registry`` provider (test-инжекция)."""
    _overrides["connector_registry"] = registry


def get_connector_registry_errors_provider() -> Any:
    """Возвращает класс исключения ``ConnectorNotRegisteredError``.

    Используется ``admin_connectors.py`` для типизированной обработки ошибок
    reload без прямого импорта ``infrastructure.registry``.
    """
    if "connector_registry_errors" in _overrides:
        return _overrides["connector_registry_errors"]
    module = resolve_module("registry")
    return module.ConnectorNotRegisteredError


# ─────────────── CDC client (Debezium) ───────────────


def get_cdc_client_provider() -> Any:
    """Возвращает singleton ``CDCClient`` (см. ``CDCClientProtocol``)."""
    if "cdc_client" in _overrides:
        return _overrides["cdc_client"]
    module = resolve_module("clients.external.cdc")
    return module.get_cdc_client()


def set_cdc_client_provider(client: Any) -> None:
    """Установить override для ``cdc_client`` provider (test-инжекция)."""
    _overrides["cdc_client"] = client


# ─────────────── S3 service ───────────────


def get_s3_service_provider() -> Any:
    """Возвращает singleton ``S3Service`` (см. ``S3Protocol``)."""
    if "s3_service" in _overrides:
        return _overrides["s3_service"]
    module = resolve_module("external_apis.s3")
    return module.get_s3_service_dependency()


def set_s3_service_provider(service: Any) -> None:
    """Установить override для ``s3_service`` provider (test-инжекция)."""
    _overrides["s3_service"] = service


__all__ = (
    "get_cdc_client_provider",
    "get_clickhouse_client_provider",
    "get_connector_config_store_provider",
    "get_connector_registry_errors_provider",
    "get_connector_registry_provider",
    "get_file_repo_provider",
    "get_mongo_client_provider",
    "get_s3_service_provider",
    "set_cdc_client_provider",
    "set_clickhouse_client_provider",
    "set_connector_config_store_provider",
    "set_connector_registry_provider",
    "set_file_repo_provider",
    "set_mongo_client_provider",
    "set_s3_service_provider",
)


# ─── S68 M2-#11 batch 3: Dask backend provider ───────────────────────


def get_dask_backend_provider() -> Any:
    """Возвращает singleton :func:\`get_dask_backend\` (см. ``DaskBackend``).

    S68 M2-#11 batch 3: lazy resolve для dsl/processors/dask_compute.py.
    Был inline: ``from src.backend.infrastructure.execution.dask_backend import get_dask_backend``
    (module-level import → cycle risk с infrastructure layer).

    Использует lazy resolve_module — НЕ тянет dask при module import.
    """
    if "dask_backend" in _overrides:
        return _overrides["dask_backend"]
    module = resolve_module("execution.dask_backend")
    return module.get_dask_backend


def set_dask_backend_provider(backend: Any) -> None:
    """Test-override для dask_backend (Sprint 68+)."""
    _overrides["dask_backend"] = backend


# ─── S74 M2-#11 batch 9: Outbox writer provider ────────────────────


def get_outbox_writer_provider() -> Any:
    """Возвращает :func:\`write\` (outbox writer).

    S74 M2-#11 batch 9: lazy resolve для dsl/processors/business.py.
    Был inline: ``from src.backend.infrastructure.repositories.outbox import
    write as default_writer`` (lazy inside method body).

    Использует lazy resolve_module — НЕ тянет outbox при module import.
    """
    if "outbox_writer" in _overrides:
        return _overrides["outbox_writer"]
    module = resolve_module("repositories.outbox")
    return module.write


def set_outbox_writer_provider(writer: Any) -> None:
    """Test-override для outbox writer (Sprint 74+)."""
    _overrides["outbox_writer"] = writer


# ─── S75 M2-#11 batch 10: External DB registry provider ──────────


def get_external_db_registry_provider() -> Any:
    """Возвращает :func:\`get_external_db_registry\` (DB registry singleton).

    S75 M2-#11 batch 10: lazy resolve для dsl/processors/batch.py.
    Был inline: ``from src.backend.infrastructure.database.database import
    get_external_db_registry`` (lazy через module-level _lazy_get_*).

    Использует lazy resolve_module — НЕ тянет database при module import.
    """
    if "external_db_registry" in _overrides:
        return _overrides["external_db_registry"]
    module = resolve_module("database.database")
    return module.get_external_db_registry


def set_external_db_registry_provider(registry: Any) -> None:
    """Test-override для external DB registry (Sprint 75+)."""
    _overrides["external_db_registry"] = registry
