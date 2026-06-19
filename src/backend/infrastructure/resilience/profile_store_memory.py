"""In-memory реализация :class:`ResilienceProfileStore` (S13 K2 W5).

Используется для dev_light и unit-тестов; на production подключается
:class:`ResilienceProfilePgStore` (через Alembic-миграцию ``2026_05_21_*``).

Per-tenant resolution: tenant-override → global fallback.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.backend.core.resilience.resilience_profile import ResilienceProfile

__all__ = ("InMemoryResilienceProfileStore",)


class InMemoryResilienceProfileStore:
    """In-memory implementation: ``dict[(tenant_id|None, name), ResilienceProfile]``."""

    def __init__(self) -> None:
        self._data: dict[tuple[str | None, str], ResilienceProfile] = {}
        self._lock = asyncio.Lock()

    async def get(
        self, name: str, *, tenant_id: str | None = None
    ) -> ResilienceProfile | None:
        """Get resilience profile by name.

        Args:
            name: Profile name.
            tenant_id: Optional tenant scope.

        Returns:
            Profile if found, None otherwise.
        """
        async with self._lock:
            if tenant_id is not None:
                tenant_override = self._data.get((tenant_id, name))
                if tenant_override is not None:
                    return tenant_override
            return self._data.get((None, name))

    async def list(self, *, tenant_id: str | None = None) -> list[ResilienceProfile]:
        """List all resilience profiles.

        Args:
            tenant_id: Optional tenant scope.

        Returns:
            List of profiles.
        """
        async with self._lock:
            # effective: tenant override (если есть) перекрывает global.
            effective: dict[str, ResilienceProfile] = {}
            for (tid, name), prof in self._data.items():
                if tid is None:
                    effective.setdefault(name, prof)
            if tenant_id is not None:
                for (tid, name), prof in self._data.items():
                    if tid == tenant_id:
                        effective[name] = prof
            return list(effective.values())

    async def upsert(
        self, profile: ResilienceProfile, *, tenant_id: str | None = None
    ) -> ResilienceProfile:
        """Create or update a resilience profile.

        Args:
            profile: Profile to upsert.
            tenant_id: Optional tenant scope.

        Returns:
            Upserted profile.
        """
        async with self._lock:
            self._data[(tenant_id, profile.name)] = profile
            return profile

    async def delete(self, name: str, *, tenant_id: str | None = None) -> bool:
        """Delete a resilience profile.

        Args:
            name: Profile name.
            tenant_id: Optional tenant scope.

        Returns:
            True if deleted, False if not found.
        """
        async with self._lock:
            return self._data.pop((tenant_id, name), None) is not None
