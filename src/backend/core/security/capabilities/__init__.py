"""ADR-044 — capability runtime: vocabulary, gate, matchers, errors.

Public API подпакета. Использовать как
``from src.backend.core.security.capabilities import CapabilityGate, CapabilityRef``.
"""

from src.backend.core.security.capabilities.audit import (  # noqa: F401 — re-export
    CapabilityAuditEvent,
    CapabilityAuditEventKind,
    log_capability_event,
)
from src.backend.core.security.capabilities.errors import (  # noqa: F401 — re-export
    CapabilityDeniedError,
    CapabilityError,
    CapabilityNotFoundError,
    CapabilitySupersetError,
)
from src.backend.core.security.capabilities.gate import (  # noqa: F401 — re-export
    AuditCallback,
    CapabilityGate,
    check_capabilities_subset,
)
from src.backend.core.security.capabilities.matchers import (  # noqa: F401 — re-export
    ExactAliasMatcher,
    GlobScopeMatcher,
    ScopeMatcher,
    SegmentedGlobMatcher,
    URISchemeMatcher,
)
from src.backend.core.security.capabilities.models import (  # noqa: F401 — re-export
    CAPABILITY_NAME_PATTERN,
    DEFAULT_CAPABILITY_CATALOG,
    CapabilityRef,
)
from src.backend.core.security.capabilities.policy import (  # noqa: F401 — re-export
    CapabilityPolicy,
    CapabilityRule,
    PolicyDecision,
)
from src.backend.core.security.capabilities.tenant import (  # noqa: F401 — re-export
    SYSTEM_TENANT_ID,
    CapabilityTenant,
    TenantContext,
)
from src.backend.core.security.capabilities.vocabulary import (  # noqa: F401 — re-export
    CapabilityDef,
    CapabilityVocabulary,
    build_default_vocabulary,
)

__all__ = (
    "CAPABILITY_NAME_PATTERN",
    "DEFAULT_CAPABILITY_CATALOG",
    "SYSTEM_TENANT_ID",
    "AuditCallback",
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
    "CapabilityTenant",
    "CapabilityVocabulary",
    "ExactAliasMatcher",
    "GlobScopeMatcher",
    "PolicyDecision",
    "ScopeMatcher",
    "SegmentedGlobMatcher",
    "TenantContext",
    "URISchemeMatcher",
    "build_default_vocabulary",
    "check_capabilities_subset",
    "log_capability_event",
)
