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

from src.backend.core.domain.models.base import (
    Base,
    BaseModel,
    mapper_registry,
    metadata,
    nullable_str,
)
from src.backend.core.domain.models.cert import CertHistory, CertRecord
from src.backend.core.domain.models.dsl_snapshot import DslSnapshot
from src.backend.core.domain.models.files import File  # S168 W14 P2-10: OrderFile moved to extensions/core_entities/files/
from src.backend.core.domain.models.langmem_models import (
    LangMemEpisodic,
    LangMemProcedural,
)
from src.backend.core.domain.models.orderkinds import OrderKind
from src.backend.core.domain.models.orders import Order
from src.backend.core.domain.models.outbox import OutboxMessage
from src.backend.core.domain.models.rule_engine import (
    RuleEngineBase,
    RuleEngineRulesetORM,
)
from src.backend.core.domain.models.users import User
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
    "mapper_registry",
    "metadata",
    "nullable_str",
    # cert
    "CertHistory",
    "CertRecord",
    # dsl_snapshot
    "DslSnapshot",
    # files
    "File",
    # S168 W14 P2-10: OrderFile moved to extensions/core_entities/files/
    # langmem
    "LangMemEpisodic",
    "LangMemProcedural",
    # orderkinds
    "OrderKind",
    # orders
    "Order",
    # outbox
    "OutboxMessage",
    # rule_engine
    "RuleEngineBase",
    "RuleEngineRulesetORM",
    # users
    "User",
    # workflow_event
    "WorkflowEvent",
    "WorkflowEventType",
    # workflow_instance
    "WorkflowInstance",
    "WorkflowStatus",
)
