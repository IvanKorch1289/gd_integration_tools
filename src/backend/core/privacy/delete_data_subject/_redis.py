"""Redis ErasureAdapter — SCAN + UNLINK для subject-related cache keys.

W9 P2-13 Phase 3 (cycle 153): извлечено из ``core/privacy/delete_data_subject.py``
(691 LOC god-module).

Реальная имплементация: SCAN match ``*subject_id*`` для разных префиксов
(user, session, tenant cache keys) и UNLINK всех найденных ключей.

Back-compat: ``core/privacy/delete_data_subject.py`` продолжает re-export
``RedisErasureAdapter`` через thin ``__init__.py`` shim (см. ADR-0328).
"""

from __future__ import annotations

import time
from typing import Any

from src.backend.core.privacy.delete_data_subject._types import (
    AdapterResult,
    ErasureResultStatus,
    ErasureStrategy,
)


class RedisErasureAdapter:
    """Redis adapter — SCAN + UNLINK для subject-related cache keys."""

    name = "redis"

    # Cache key prefixes для SCAN.
    DEFAULT_PREFIXES = (
        "user:",
        "session:",
        "tenant:",
        "auth:",
        "cache:user:",
        "cache:session:",
    )

    def __init__(
        self, redis_client: Any = None, key_prefixes: tuple[str, ...] | None = None
    ) -> None:
        """Инициализация.

        Args:
            redis_client: async redis client (redis.asyncio.Redis).
            key_prefixes: префиксы для SCAN match. None → DEFAULT_PREFIXES.
        """
        self._redis = redis_client
        self._prefixes = key_prefixes or self.DEFAULT_PREFIXES

    async def execute(
        self,
        subject_id: str,
        subject_type: str,
        strategy: ErasureStrategy,
        correlation_id: str,
        *,
        explicit_tenant_id: str | None = None,
    ) -> AdapterResult:
        """Execute cache invalidation через SCAN + UNLINK.

        Per ADR-0345/v5 prompt Option A: tenant-awareness.
        - If ``explicit_tenant_id`` provided OR ``current_tenant()`` from
          TenantContext available → SCAN pattern restricted by tenant prefix.
        - If neither available → legacy behavior (caller's responsibility).

        Backwards-compatible: new param is keyword-only optional.
        Existing callers (no TenantContext setup) continue working.
        """
        from src.backend.core.tenancy import get_tenant_id

        start = time.monotonic()
        try:
            redis = self._redis
            if redis is None:
                return AdapterResult(
                    adapter_name=self.name,
                    status=ErasureResultStatus.SKIPPED,
                    duration_ms=(time.monotonic() - start) * 1000,
                    error="redis_client not configured",
                )

            # Per ADR-0345: resolve effective_tenant_id.
            effective_tenant = (
                explicit_tenant_id if explicit_tenant_id is not None
                else get_tenant_id()
            )
            # Build prefix list — original + tenant prefix if tenant resolved.
            prefixes_to_scan = self._prefixes
            if effective_tenant:
                tenant_prefix = f"tenant:{effective_tenant}:"
                prefixes_to_scan = (*self._prefixes, tenant_prefix)

            keys_to_delete: set[bytes | str] = set()
            for prefix in prefixes_to_scan:
                # SCAN cursor-based iteration (non-blocking).
                cursor = 0
                while True:
                    cursor, keys = await redis.scan(
                        cursor=cursor, match=f"*{prefix}{subject_id}*", count=100
                    )
                    keys_to_delete.update(keys)
                    if cursor == 0:
                        break

            deleted = 0
            if keys_to_delete:
                # UNLINK — async, не блокирует Redis.
                deleted = await redis.unlink(*keys_to_delete)

            duration = (time.monotonic() - start) * 1000
            return AdapterResult(
                adapter_name=self.name,
                status=ErasureResultStatus.SUCCESS,
                duration_ms=duration,
                records_affected=deleted,
            )
        except Exception as exc:
            duration = (time.monotonic() - start) * 1000
            return AdapterResult(
                adapter_name=self.name,
                status=ErasureResultStatus.FAILED,
                duration_ms=duration,
                error=f"{type(exc).__name__}: {exc}",
            )
