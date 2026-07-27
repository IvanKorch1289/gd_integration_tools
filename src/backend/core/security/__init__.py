"""S67 W1: PEP 420 namespace package для ``src.backend.core.security``.

AuthN/AuthZ primitives: capability gates, policy resolver, OAuth, LDAP.
Public API — на уровне подпакетов.
"""

from src.backend.core.security.module_whitelist import (
    EmptyWhitelistMode,
    validate_module_whitelist,
)

__all__ = ("EmptyWhitelistMode", "validate_module_whitelist")
