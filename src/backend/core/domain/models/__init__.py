"""Canonical SQLAlchemy ORM models (S106 W1 D5 B1 + W3 D5 B2a).

DEEP-RESEARCH D5 (🔴 High): SQLAlchemy models в ``infrastructure/`` нарушают
layer policy V22 (extensions должны импортировать ТОЛЬКО ``core/`` +
capability-checked фасады, не ``infrastructure/`` напрямую).

S106 W1 переносит 6 Risk A моделей (cert, dsl_snapshot, langmem_models,
outbox, rule_engine, users) + carrier ``base.py`` в
``core/domain/models/``. S106 W3 (D5 B2a) переносит orderkinds.
S106 W3-W4 (D5 B2b+c) перенесут orders, files. S106 W5 (D5 B3) перенесёт
workflow_instance, workflow_event. Hard delete shim'ов — S106 W5.

Back-compat shim (1 sprint grace) в
``src/backend/infrastructure/database/models/`` — re-export с
``DeprecationWarning`` (аналогично S95 W4 AuthGateway + S103 W3
``core/audit/facade.py`` patterns).

References:
- ADR-0188 (D5 plan)
- ``docs/migration/d5-models-to-core.md`` (B1-B3 plan)
- ``docs/adr/0191-sprint-106-closure.md`` (S106 closure, planned)

"""

from __future__ import annotations

# Импорт моделей из extensions в core — УДАЛЁН 2026-10-06 (R-V15-16).
# Раньше здесь шёл реэкспорт File/Order/OrderKind/User/OrderFile из
# extensions/core_entities/*/domain/models.py. Это создавало прямую
# зависимость ``core → extensions`` и попадало в allowlist гейта слоёв.
#
# После инверсии таблицы регистрируются на ``Base.metadata`` самими
# расширениями (см. ``extensions/core_entities/<name>/domain/__init__.py``).
# Контракт остаётся:
#
#   * ``Base`` / ``BaseModel`` / ``metadata`` / ``mapper_registry`` — ядро;
#   * доменные модели (``User``, ``Order``, ...) — extensions;
#   * потребители импортируют их из extensions напрямую
#     (``extensions.core_entities.X.domain.models``).
#
# Регистрация ORM для миграций идёт через
# :func:`load_plugin_manifests_for_migrations` (см.
# ``services/plugins/loader/models_discovery.py`` и
# ``infrastructure/resilience/snapshot_job.py``).
from src.backend.core.domain.models.base import (
    Base,
    BaseModel,
    mapper_registry,
    metadata,
    nullable_str,
)
from src.backend.core.domain.models.cert import CertHistory, CertRecord
from src.backend.core.domain.models.dsl_snapshot import DslSnapshot
from src.backend.core.domain.models.langmem_models import (
    LangMemEpisodic,
    LangMemProcedural,
)
from src.backend.core.domain.models.outbox import OutboxMessage
from src.backend.core.domain.models.rule_engine import (
    RuleEngineBase,
    RuleEngineRulesetORM,
)
from src.backend.core.domain.models.scheduler_run_history import (
    SchedulerRunHistory as SchedulerRunHistory,
)
from src.backend.core.domain.models.workflow_event import (
    WorkflowEvent,
    WorkflowEventType,
)
from src.backend.core.domain.models.workflow_instance import (
    WorkflowInstance,
    WorkflowStatus,
)

__all__ = (
    # base
    "Base",
    "BaseModel",
    # cert
    "CertHistory",
    "CertRecord",
    # dsl_snapshot
    "DslSnapshot",
    # langmem
    "LangMemEpisodic",
    "LangMemProcedural",
    # outbox
    "OutboxMessage",
    # rule_engine
    "RuleEngineBase",
    "RuleEngineRulesetORM",
    # scheduler
    "SchedulerRunHistory",
    # workflow_event
    "WorkflowEvent",
    "WorkflowEventType",
    # workflow_instance
    "WorkflowInstance",
    "WorkflowStatus",
    "mapper_registry",
    "metadata",
    "nullable_str",
)
