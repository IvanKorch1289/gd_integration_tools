"""Tenant-scoped memory — pure-Python namespace isolation (Wave 3 #24)."""

from __future__ import annotations

import fnmatch
import logging
import time
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

__all__ = ("MemoryAccessPolicy", "MemoryEntry", "TenantMemoryStore", "get_memory_store")


@dataclass(slots=True)
class MemoryEntry:
    """Single memory record."""

    tenant_id: str
    key: str
    value: Any
    created_at: float = 0.0
    updated_at: float = 0.0
    expires_at: float | None = None
    tags: tuple[str, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)

    def is_expired(self, now: float | None = None) -> bool:
        if self.expires_at is None:
            return False
        current = now if now is not None else time.time()
        return current >= self.expires_at


@dataclass(slots=True)
class MemoryAccessPolicy:
    """Access policy для tenant memory.

    Attributes:
        allowed_tenants: Whitelist of tenant IDs (None = all).
        blocked_keys: List of glob patterns to block.
        read_only: True = no put() allowed.
    """

    allowed_tenants: tuple[str, ...] | None = None
    blocked_keys: tuple[str, ...] = ()
    read_only: bool = False


class TenantMemoryStore:
    """Per-tenant memory store with namespace isolation.

    Pure-Python, in-memory. Production → Redis / vector DB.
    """

    def __init__(self, policy: MemoryAccessPolicy | None = None) -> None:
        self._store: dict[str, dict[str, MemoryEntry]] = {}
        self._policy = policy or MemoryAccessPolicy()

    @property
    def policy(self) -> MemoryAccessPolicy:
        return self._policy

    def set_policy(self, policy: MemoryAccessPolicy) -> None:
        self._policy = policy

    # ─── CRUD ─────────────────────────────────────────────

    def put(
        self,
        tenant_id: str,
        key: str,
        value: Any,
        *,
        ttl_seconds: float | None = None,
        tags: tuple[str, ...] = (),
        metadata: dict[str, Any] | None = None,
    ) -> MemoryEntry:
        """Store key=value для tenant."""
        if not self._check_tenant_allowed(tenant_id):
            raise PermissionError(f"Tenant '{tenant_id}' not allowed by policy")
        if self._policy.read_only:
            raise PermissionError("Memory store is read-only")
        if self._is_key_blocked(key):
            raise PermissionError(f"Key '{key}' blocked by policy")

        now = time.time()
        entry = MemoryEntry(
            tenant_id=tenant_id,
            key=key,
            value=value,
            created_at=now,
            updated_at=now,
            expires_at=(now + ttl_seconds) if ttl_seconds else None,
            tags=tags,
            metadata=metadata or {},
        )
        self._store.setdefault(tenant_id, {})[key] = entry
        return entry

    def get(self, tenant_id: str, key: str) -> Any:
        """Get value для tenant.key. Raises KeyError if missing/expired."""
        if not self._check_tenant_allowed(tenant_id):
            raise PermissionError(f"Tenant '{tenant_id}' not allowed by policy")
        if self._is_key_blocked(key):
            raise PermissionError(f"Key '{key}' blocked by policy")
        entry = self._get_entry(tenant_id, key)
        if entry is None:
            raise KeyError(f"Key '{tenant_id}:{key}' not found")
        return entry.value

    def try_get(self, tenant_id: str, key: str, default: Any = None) -> Any:
        """Get value или default. No exception."""
        try:
            return self.get(tenant_id, key)
        except (KeyError, PermissionError):
            return default

    def delete(self, tenant_id: str, key: str) -> bool:
        """Delete key. Returns True if existed."""
        if not self._check_tenant_allowed(tenant_id):
            raise PermissionError(f"Tenant '{tenant_id}' not allowed by policy")
        if self._is_key_blocked(key):
            raise PermissionError(f"Key '{key}' blocked by policy")
        tenant_data = self._store.get(tenant_id, {})
        if key in tenant_data:
            del tenant_data[key]
            return True
        return False

    def exists(self, tenant_id: str, key: str) -> bool:
        """Check if key exists (and not expired)."""
        return self._get_entry(tenant_id, key) is not None

    # ─── Search / list ────────────────────────────────────

    def list_keys(self, tenant_id: str) -> list[str]:
        """List all keys для tenant (excluding expired)."""
        if not self._check_tenant_allowed(tenant_id):
            raise PermissionError(f"Tenant '{tenant_id}' not allowed by policy")
        tenant_data = self._store.get(tenant_id, {})
        now = time.time()
        return [k for k, entry in tenant_data.items() if not entry.is_expired(now)]

    def search(self, tenant_id: str, pattern: str) -> list[MemoryEntry]:
        """Search entries by key pattern (glob, e.g. 'user.pref.*')."""
        if not self._check_tenant_allowed(tenant_id):
            raise PermissionError(f"Tenant '{tenant_id}' not allowed by policy")
        tenant_data = self._store.get(tenant_id, {})
        now = time.time()
        result: list[MemoryEntry] = []
        for k, entry in tenant_data.items():
            if entry.is_expired(now):
                continue
            if fnmatch.fnmatch(k, pattern):
                result.append(entry)
        return result

    # ─── Bulk operations ──────────────────────────────────

    def clear_tenant(self, tenant_id: str) -> int:
        """Clear all entries для tenant. Returns count removed."""
        if not self._check_tenant_allowed(tenant_id):
            raise PermissionError(f"Tenant '{tenant_id}' not allowed by policy")
        if self._policy.read_only:
            raise PermissionError("Memory store is read-only")
        count = len(self._store.get(tenant_id, {}))
        self._store.pop(tenant_id, None)
        return count

    def cleanup_expired(self) -> int:
        """Remove all expired entries across all tenants. Returns count."""
        now = time.time()
        count = 0
        for tenant_data in self._store.values():
            expired_keys = [k for k, e in tenant_data.items() if e.is_expired(now)]
            for k in expired_keys:
                del tenant_data[k]
                count += 1
        return count

    # ─── Admin ────────────────────────────────────────────

    def list_tenants(self) -> list[str]:
        """List all tenants с active memory."""
        return [t for t, data in self._store.items() if data]

    def size(self) -> int:
        """Total entries (across all tenants)."""
        return sum(len(data) for data in self._store.values())

    def tenant_size(self, tenant_id: str) -> int:
        """Entries for specific tenant."""
        return len(self._store.get(tenant_id, {}))

    def clear(self) -> None:
        """Clear all data (admin only)."""
        self._store.clear()

    # ─── Helpers ──────────────────────────────────────────

    def _get_entry(self, tenant_id: str, key: str) -> MemoryEntry | None:
        tenant_data = self._store.get(tenant_id, {})
        entry = tenant_data.get(key)
        if entry is None:
            return None
        if entry.is_expired():
            del tenant_data[key]
            return None
        return entry

    def _check_tenant_allowed(self, tenant_id: str) -> bool:
        if self._policy.allowed_tenants is None:
            return True
        return tenant_id in self._policy.allowed_tenants

    def _is_key_blocked(self, key: str) -> bool:
        for pattern in self._policy.blocked_keys:
            if fnmatch.fnmatch(key, pattern):
                return True
        return False


_store: TenantMemoryStore | None = None


def get_memory_store() -> TenantMemoryStore:
    global _store
    if _store is None:
        _store = TenantMemoryStore()
    return _store


def reset_memory_store() -> None:
    global _store
    _store = None
