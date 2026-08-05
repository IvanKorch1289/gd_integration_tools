"""Structural protocol for CapabilityGate mixins.

Breaks the circular dependency between ``CapabilityGate`` and its mixins
while giving mypy enough information about the private attributes the
mixins expect.
"""

from __future__ import annotations

from threading import Lock
from typing import Any, Protocol

from src.backend.core.security.capabilities.models import CapabilityRef
from src.backend.core.security.capabilities.policy import CapabilityPolicy
from src.backend.core.security.capabilities.vocabulary import CapabilityVocabulary


class _CapabilityGateProtocol(Protocol):
    """Private shape shared by CapabilityGate mixins."""

    _vocabulary: CapabilityVocabulary
    _audit: Any
    _declarations: dict[str, dict[str, CapabilityRef]]
    _cache: dict[tuple[str, str, str | None], bool]
    _tenant_cache: dict[tuple[str, str, str, str | None], bool]
    _lru_size: int
    _tenant_declarations: dict[str, dict[str, dict[str, CapabilityRef]]]
    _policy: CapabilityPolicy | None
    # D-AUDIT-98 (S183 W1.1): coarse-grained lock protecting all reads/mutations
    # of ``_cache`` and ``_tenant_cache``. ``threading.Lock`` (not asyncio.Lock)
    # because callers may be sync (RouteLoader) or async (FastAPI handlers) —
    # a thread lock serializes both. Acquired only for short critical sections
    # (dict read + LRU pop + write), so contention is negligible.
    _lock: Lock

    def _emit_audit(self, event: dict[str, object]) -> None: ...

    def _cache_granted(self, key: tuple[str, str, str | None]) -> None: ...

    def _tenant_cache_granted(self, key: tuple[str, str, str, str | None]) -> None: ...

    def _invalidate_plugin(self, plugin: str) -> None: ...

    def _invalidate_tenant(self, tenant: str, principal: str | None = None) -> None: ...
