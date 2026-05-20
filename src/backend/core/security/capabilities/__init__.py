"""ADR-044 — capability runtime: vocabulary, gate, matchers, errors.

Public API подпакета. Использовать как
``from src.backend.core.security.capabilities import CapabilityGate, CapabilityRef``.
"""

from src.backend.core.security.capabilities.audit import (
    CapabilityAuditEvent,
    CapabilityAuditEventKind,
    log_capability_event,
)
from src.backend.core.security.capabilities.errors import (
    CapabilityDeniedError,
    CapabilityError,
    CapabilityNotFoundError,
    CapabilitySupersetError,
)
from src.backend.core.security.capabilities.gate import (
    AuditCallback,
    CapabilityGate,
    check_capabilities_subset,
)
from src.backend.core.security.capabilities.matchers import (
    ExactAliasMatcher,
    GlobScopeMatcher,
    ScopeMatcher,
    SegmentedGlobMatcher,
    URISchemeMatcher,
)
from src.backend.core.security.capabilities.models import (
    CAPABILITY_NAME_PATTERN,
    DEFAULT_CAPABILITY_CATALOG,
    CapabilityRef,
)
from src.backend.core.security.capabilities.policy import (
    CapabilityPolicy,
    CapabilityRule,
    PolicyDecision,
)
from src.backend.core.security.capabilities.vocabulary import (
    CapabilityDef,
    CapabilityVocabulary,
    build_default_vocabulary,
)

__all__ = (
    "AuditCallback",
    "CAPABILITY_NAME_PATTERN",
    "CapabilityAuditEvent",
    "CapabilityAuditEventKind",
    "CapabilityDef",
    "CapabilityDeniedError",
    "CapabilityError",
    "CapabilityGate",
    "CapabilityNotFoundError",
    "CapabilityPolicy",
    "CapabilityRef",
    "CapabilityRule",
    "CapabilitySupersetError",
    "CapabilityVocabulary",
    "DEFAULT_CAPABILITY_CATALOG",
    "ExactAliasMatcher",
    "GlobScopeMatcher",
    "PolicyDecision",
    "ScopeMatcher",
    "SegmentedGlobMatcher",
    "URISchemeMatcher",
    "build_default_vocabulary",
    "check_capabilities_subset",
    "log_capability_event",
)
