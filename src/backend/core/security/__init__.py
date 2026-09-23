"""S67 W1: PEP 420 namespace package для ``src.backend.core.security``.

AuthN/AuthZ primitives: capability gates, policy resolver, OAuth, LDAP.
Public API — на уровне подпакетов.
"""

from src.backend.core.security.module_whitelist import (
    EmptyWhitelistMode,
    validate_module_whitelist,
)
from src.backend.core.security.restricted_unpickler import (
    DEFAULT_ALLOWLIST,
    RestrictedUnpickler,
    safe_loads,
)

__all__ = (
    "DEFAULT_ALLOWLIST",
    "EmptyWhitelistMode",
    "RestrictedUnpickler",
    "safe_loads",
    "validate_module_whitelist",
)
