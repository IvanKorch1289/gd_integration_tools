"""ClickHouse admin client facade (capability-checked entrypoint).

S45 follow-up to DEEP-AUDIT-2026-06-22.md P0 #3 (entrypoints → infrastructure
cross-layer violation). Admin-эндпоинты ``admin_workflow_audit.py`` и
``admin_workflow_cost.py`` напрямую lazy-импортировали
``src.backend.infrastructure.clients.storage.clickhouse_admin_client``.

Single-Entry per Concern (AGENTS.md): entrypoints → services/ → infrastructure/.
Этот модуль — тонкая обёртка-фасад поверх infrastructure-имплементации.

Canonical impl остаётся в:
    ``src.backend.infrastructure.clients.storage.clickhouse_admin_client``

Здесь только re-export public symbols. Никакой дополнительной логики.
При изменении infrastructure-имплементации — менять здесь не нужно.
"""

from __future__ import annotations

from src.backend.infrastructure.clients.storage.clickhouse_admin_client import (
    AdminClickHouseClient,
    get_admin_clickhouse_client,
)

__all__ = ("AdminClickHouseClient", "get_admin_clickhouse_client")
