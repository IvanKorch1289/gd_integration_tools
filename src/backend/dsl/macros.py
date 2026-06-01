"""Shim-модуль для backwards-compat импорта legacy DSL macros.

Sprint 7 / K3 (``[wave:s7/k3-dsl-blueprints-migrate]``):
    Реальная реализация перенесена в
    ``src.backend.dsl.blueprints.macros``. Этот модуль сохранён для
    обратной совместимости импортов вида::

        from src.backend.dsl.macros import etl_pipeline, safe_action

    Под feature flag ``dsl_blueprints_migrate`` (default-OFF) выдаёт
    ``DeprecationWarning`` при первом импорте, чтобы плагинам / extensions
    был ясен срок поддержки (1-2 sprint).

Срок жизни:
    Sprint 7-8 — shim активен, deprecation-warning при feature_flag=True.
    Sprint 9+ — удаление после grep-чистки всех потребителей.
"""

from __future__ import annotations

import warnings

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
    "ai_qa_pipeline",
    "crud_with_audit",
    "etl_pipeline",
    "format_bridge",
    "polling_etl",
    "safe_action",
    "scrape_and_store",
    "webhook_relay",
)


def _emit_deprecation_once() -> None:
    """Выдаёт deprecation-warning один раз, если активен feature flag.

    Проверка флага защищена try/except: на ранних стадиях bootstrap
    (импорты до загрузки settings) исключения не должны ломать импорт.
    """
    try:
        from src.backend.core.config.features import feature_flags

        if getattr(feature_flags, "dsl_blueprints_migrate", False):
            warnings.warn(
                "src.backend.dsl.macros перемещён в "
                "src.backend.dsl.blueprints.macros (Sprint 7 K3). "
                "Импортируй через 'from src.backend.dsl.blueprints "
                "import <name>' либо 'from src.backend.dsl.blueprints.macros "
                "import <name>'. Shim будет удалён в Sprint 9.",
                DeprecationWarning,
                stacklevel=3,
            )
    except Exception:  # noqa: BLE001, S110
        # Bootstrap-окружение без settings — молча игнорируем.
        # Deprecation-warning не критичен, чтобы из-за него падал импорт.
        pass


_emit_deprecation_once()
