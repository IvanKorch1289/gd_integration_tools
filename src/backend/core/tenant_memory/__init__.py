"""Tenant-scoped memory — namespace isolation helper (Wave 3 #24).

Проблема:
    Память агента может смешать данные тенантов:
    - Без namespace → cross-tenant data leak.
    - Без TTL → stale data.
    - Без access policy → любой код может читать/писать.

Решение:
    ``TenantMemory`` — pure-Python namespace isolation:

    1. ``MemoryEntry`` — единичная запись (key/value + metadata).
    2. ``TenantMemoryStore`` — per-tenant namespaces.
    3. ``put(tenant, key, value)`` / ``get(tenant, key)`` — typed access.
    4. ``search(tenant, pattern)`` — pattern matching.
    5. ``clear_tenant(tenant)`` — bulk delete per tenant.
    6. ``MemoryAccessPolicy`` — read/write permission check.

Использование::

    from src.backend.core.tenant_memory import (  # noqa: F401 — re-export
        TenantMemoryStore, MemoryEntry, get_memory_store,
    )

    store = get_memory_store()
    store.put("tenant-1", "user_pref.theme", "dark")
    value = store.get("tenant-1", "user_pref.theme")  # "dark"
    # Cross-tenant → KeyError.
    store.get("tenant-2", "user_pref.theme")  # KeyError
"""

from __future__ import annotations

from src.backend.core.tenant_memory.store import (  # noqa: F401 — re-export
    MemoryAccessPolicy,
    MemoryEntry,
    TenantMemoryStore,
    get_memory_store,
)

__all__ = ("MemoryAccessPolicy", "MemoryEntry", "TenantMemoryStore", "get_memory_store")
