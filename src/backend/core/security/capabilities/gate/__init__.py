"""CapabilityGate package (S54 W4 decomp from gate.py 629 LOC).

17 methods decomposed в 4 mixin files:
- ``declaration_mixin.py`` (5): declare, revoke, declare_tenant, revoke_tenant, list_allocated_tenant
- ``check_mixin.py`` (2): check, check_tenant (the BIG methods 132 + 128 LOC)
- ``cache_mixin.py`` (6): cache + invalidation (granted caches, plugin/tenant invalidation)
- ``audit_mixin.py`` (1): _emit_audit

Core (__init__ + vocabulary + policy) остается в __init__.py.

Backward-compat: ``from src.backend.core.security.capabilities.gate import CapabilityGate`` works.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING, Any, Final

from src.backend.core.logging import get_logger
from src.backend.core.security.capabilities.errors import (
    CapabilityNotFoundError,
    CapabilitySupersetError,
)
from src.backend.core.security.capabilities.models import CapabilityRef
from src.backend.core.security.capabilities.vocabulary import (
    build_default_vocabulary,  # S79 W2 fix: S54 W4 decomp forgot import
)
from src.backend.core.security.capabilities.vocabulary import CapabilityVocabulary

if TYPE_CHECKING:
    pass

from src.backend.core.security.capabilities.gate.audit_mixin import (
    AuditMixin,  # S54 W4: MRO
)
from src.backend.core.security.capabilities.gate.cache_mixin import (
    CacheMixin,  # S54 W4: MRO
)
from src.backend.core.security.capabilities.gate.check_mixin import (
    CheckMixin,  # S54 W4: MRO
)
from src.backend.core.security.capabilities.gate.declaration_mixin import (
    DeclarationMixin,  # S54 W4: MRO
)

__all__ = ("CapabilityGate",)


# --- Module-level constants (S54 W4 decomp: preserve original constants) ---
AuditCallback = Callable[[dict[str, object]], None]

_DEFAULT_LRU_SIZE: Final[int] = 1024

# --- End constants ---


class CapabilityGate(DeclarationMixin, CheckMixin, CacheMixin, AuditMixin):
    """Capability Gate (4 mixins = 14 methods + 3 core)."""

    # S79 W2 fix: removed `__slots__ = ()` (S54 W4 decomp forgot про
    # instance attrs `_vocabulary` etc). Same pattern as S74 W4
    # NotebookExecutionService / S76 W3 AIPolicyEnforcer / S76 W4 fix.
    def __init__(
        self,
        *,
        vocabulary: CapabilityVocabulary | None = None,
        audit: AuditCallback | None = None,
        lru_size: int = _DEFAULT_LRU_SIZE,
        policy: "CapabilityPolicy | None" = None,
    ) -> None:
        self._vocabulary = vocabulary or build_default_vocabulary()
        self._audit = audit
        self._declarations: dict[str, dict[str, CapabilityRef]] = {}
        self._cache: dict[tuple[str, str, str | None], bool] = {}
        self._lru_size = lru_size
        # Per-tenant storage: tenant_id → principal_id → capability_name → ref.
        self._tenant_declarations: dict[str, dict[str, dict[str, CapabilityRef]]] = {}
        # Per-tenant LRU cache: (tenant, principal, capability, scope) → bool.
        self._tenant_cache: dict[tuple[str, str, str, str | None], bool] = {}
        self._policy: "CapabilityPolicy | None" = policy

    @property
    def vocabulary(self) -> CapabilityVocabulary:
        """Доступ к registry для админ-UI и DSL-Linter."""
        return self._vocabulary

    @property
    def policy(self) -> "CapabilityPolicy | None":
        """Опц. policy, интегрированная в gate (``None`` → no policy)."""
        return self._policy


def check_capabilities_subset(
    *,
    route: str,
    route_caps: Iterable[CapabilityRef],
    plugin_caps_by_name: dict[str, tuple[CapabilityRef, ...]],
    vocabulary: CapabilityVocabulary,
) -> None:
    """Проверить инвариант ``route.capabilities ⊆ union(plugin) ∪ core_public``.

    Используется :class:`RouteLoader` при активации маршрута.

    Args:
        route: Имя маршрута (для сообщения об ошибке).
        route_caps: Capabilities, объявленные в `route.toml`.
        plugin_caps_by_name: Mapping ``plugin_name → tuple[CapabilityRef]``
            из манифестов всех плагинов из ``requires_plugins``.
        vocabulary: Registry; ``public_capabilities()`` берётся как
            «общедоступный» набор ядра.

    Raises:
        CapabilitySupersetError: Хотя бы одна capability route'а не
            покрывается объединением источников.
    """
    available: list[CapabilityRef] = []
    for caps in plugin_caps_by_name.values():
        available.extend(caps)
    # Public ядра представлены как CapabilityRef без scope (открытое
    # пространство); matcher для них трактует requested как разрешённый.
    public_names = {d.name for d in vocabulary.public_capabilities()}

    offending: list[CapabilityRef] = []
    for ref in route_caps:
        if ref.name in public_names:
            continue
        if not _is_covered(ref, available, vocabulary):
            offending.append(ref)
    if offending:
        raise CapabilitySupersetError(route=route, offending=tuple(offending))


def _is_covered(
    ref: CapabilityRef, available: list[CapabilityRef], vocabulary: CapabilityVocabulary
) -> bool:
    """Покрывается ли ``ref`` хотя бы одной capability из ``available``."""
    try:
        definition = vocabulary.get(ref.name)
    except CapabilityNotFoundError:
        return False
    for candidate in available:
        if candidate.name != ref.name:
            continue
        # Если capability scope_required=False, наличия имени достаточно.
        if not definition.scope_required:
            return True
        if candidate.scope is None or ref.scope is None:
            # public-без-scope vs scoped — несравнимы, считаем не-покрытием
            continue
        if definition.matcher.match(ref.scope, candidate.scope):
            return True
    return False
