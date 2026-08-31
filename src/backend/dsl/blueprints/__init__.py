"""DSL Blueprints — каталог готовых шаблонов интеграционных pipeline.

Sprint 7 / K3 — миграция legacy-модулей в пакет:

* ``_python_blueprints`` — Python-функции (api_normalize_persist_webhook,
  cdc_enrich_publish, file_watch_parse_validate_action,
  request_response_with_compensation). Раннее жили в
  ``src/backend/dsl/blueprints.py``.
* ``macros`` — pre-built Camel-style паттерны (etl_pipeline, webhook_relay,
  ai_qa_pipeline, safe_action, crud_with_audit, scrape_and_store,
  format_bridge, polling_etl). Раннее жили в
  ``src/backend/dsl/macros.py``.
* ``*.yaml`` — декларативные blueprint-шаблоны (ai_pipeline, api_normalize,
  cdc_enrich, saga_with_compensation), читаются runtime-loader'ом.

Public API сохранён 1:1 относительно старых модулей: импорт через
``from src.backend.dsl.blueprints import <name>`` работает после
миграции для всех функций обеих legacy-папок.

Backwards compatibility:
    * ``from src.backend.dsl.macros import X`` — поддерживается через
      shim-модуль ``src.backend.dsl.macros`` (deprecation-warning под
      feature flag ``dsl_blueprints_migrate``).
    * ``from src.backend.dsl.blueprints import X`` — старый импорт
      сохранён, теперь это пакет вместо модуля.
"""

from __future__ import annotations

from src.backend.dsl.blueprints._python_blueprints import (
    api_normalize_persist_webhook,
    cdc_enrich_publish,
    file_watch_parse_validate_action,
    request_response_with_compensation,
)
from src.backend.dsl.blueprints.macros import (
    ai_qa_pipeline,
    crud_with_audit,
    etl_pipeline,
    format_bridge,
    polling_etl,
    safe_action,
    scrape_and_store,
    webhook_relay,
)

__all__ = (
    # macros
    "ai_qa_pipeline",
    # _python_blueprints
    "api_normalize_persist_webhook",
    "cdc_enrich_publish",
    "crud_with_audit",
    "etl_pipeline",
    "file_watch_parse_validate_action",
    "format_bridge",
    "polling_etl",
    "request_response_with_compensation",
    "safe_action",
    "scrape_and_store",
    "webhook_relay",
)
