"""ClickHouse admin client facade (capability-checked entrypoint).

S45 follow-up to DEEP-AUDIT-2026-06-22.md P0 #3 (entrypoints → infrastructure
cross-layer violation).

Sprint 224 refactor: convert direct re-export to ``__getattr__``-based lazy
proxy (ponytail: thin proxy). Устраняет layer-violation
``services → infrastructure``.

Canonical impl остаётся в:
    ``src.backend.infrastructure.clients.storage.clickhouse_admin_client``
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from src.backend.infrastructure.clients.storage.clickhouse_admin_client import (
        AdminClickHouseClient,
        get_admin_clickhouse_client,
    )

__all__ = ("AdminClickHouseClient", "get_admin_clickhouse_client")


def __getattr__(name: str) -> Any:
    """Lazy proxy: import infrastructure только при lookup атрибута."""
    if name in {"AdminClickHouseClient", "get_admin_clickhouse_client"}:
        from src.backend.infrastructure.clients.storage import (
            clickhouse_admin_client as _m,
        )

        return getattr(_m, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
