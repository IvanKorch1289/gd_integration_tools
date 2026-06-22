"""LogIndexer facade для infrastructure (S44 W5, ADR-0248 follow-up).

Single entry-point для LogIndexer access из infrastructure.audit.event_log
и других infrastructure модулей. Re-export canonical
``services.io.indexers.log_indexer.LogIndexer`` + ``get_log_indexer``.

Использование::

    from src.backend.core.observability.log_indexer import get_log_indexer
    indexer = get_log_indexer()
    await indexer.index_batch(events)

Layer policy: infrastructure -> core (allowed per ALLOWED matrix).
Этот facade — единственный разрешённый путь для infrastructure доступа
к LogIndexer без layer-violation.
См. layer-linter exception для
``core/observability/log_indexer.py → services.io.indexers.log_indexer``.

S44 W5 sprint goal: убрать string-bypass в
``infrastructure/audit/event_log.py:22`` (deep-audit P0-2).
"""
from __future__ import annotations

from src.backend.services.io.indexers.log_indexer import (  # noqa: E402,F401
    LogIndexer,
    get_log_indexer,
)

__all__ = ("LogIndexer", "get_log_indexer")
