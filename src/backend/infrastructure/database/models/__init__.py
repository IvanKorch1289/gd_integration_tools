"""DEPRECATED shim — все модели в ``infrastructure/database/models/`` deprecated.

S106 W1 (D5 B1) перенёс 7 Risk A моделей (base, cert, dsl_snapshot,
langmem_models, outbox, rule_engine, users) в ``core/domain/models/``.

Этот namespace package — back-compat shim. Конкретные submodule shim'ы
выдают ``DeprecationWarning`` при импорте. Hard delete — S106 W5.

References:
- ADR-0188 (D5 plan)
- ``docs/migration/d5-models-to-core.md``
"""
