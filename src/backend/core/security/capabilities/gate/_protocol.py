"""Structural protocol for CapabilityGate mixins.

Breaks the circular dependency between ``CapabilityGate`` and its mixins
while giving mypy enough information about the private attributes the
mixins expect.
"""

from __future__ import annotations

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
    _lru_size: int
    _tenant_declarations: dict[str, dict[str, dict[str, CapabilityRef]]]
    _tenant_cache: dict[tuple[str, str, str, str | None], bool]
    _policy: CapabilityPolicy | None

    def _emit_audit(self, event: dict[str, object]) -> None: ...

    def _cache_granted(self, key: tuple[str, str, str | None]) -> None: ...

    def _tenant_cache_granted(self, key: tuple[str, str, str, str | None]) -> None: ...

    def _invalidate_plugin(self, plugin: str) -> None: ...

    def _invalidate_tenant(self, tenant: str, principal: str | None = None) -> None: ...
