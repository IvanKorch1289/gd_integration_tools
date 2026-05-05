"""ADR-044 — capability runtime: vocabulary, gate, matchers, errors.

Public API подпакета. Использовать как
``from src.core.security.capabilities import CapabilityGate, CapabilityRef``.
"""

from src.core.security.capabilities.errors import (
    CapabilityDeniedError,
    CapabilityError,
    CapabilityNotFoundError,
    CapabilitySupersetError,
)
from src.core.security.capabilities.gate import (
    AuditCallback,
    CapabilityGate,
    check_capabilities_subset,
)
from src.core.security.capabilities.matchers import (
    ExactAliasMatcher,
    GlobScopeMatcher,
    ScopeMatcher,
    SegmentedGlobMatcher,
    URISchemeMatcher,
)
from src.core.security.capabilities.models import (
    CAPABILITY_NAME_PATTERN,
    DEFAULT_CAPABILITY_CATALOG,
    CapabilityRef,
)
from src.core.security.capabilities.vocabulary import (
    CapabilityDef,
    CapabilityVocabulary,
    build_default_vocabulary,
)

__all__ = (
    "AuditCallback",
    "CAPABILITY_NAME_PATTERN",
    "CapabilityDef",
    "CapabilityDeniedError",
    "CapabilityError",
    "CapabilityGate",
    "CapabilityNotFoundError",
    "CapabilityRef",
    "CapabilitySupersetError",
    "CapabilityVocabulary",
    "DEFAULT_CAPABILITY_CATALOG",
    "ExactAliasMatcher",
    "GlobScopeMatcher",
    "ScopeMatcher",
    "SegmentedGlobMatcher",
    "URISchemeMatcher",
    "build_default_vocabulary",
    "check_capabilities_subset",
)
