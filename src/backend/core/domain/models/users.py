"""DEPRECATED: re-export shim (S168 W14 P2-10).

User model moved to
src.backend.extensions.core_entities.users.domain.models per
master prompt v8 P2-10. Will be removed в S169+.
"""
import warnings
from extensions.core_entities.users.domain.models import (  # noqa: E402,F401
    User,
    _get_password_hasher,
    argon2_exceptions,
)

warnings.warn(
    "src.backend.core.domain.models.users is deprecated "
    "(S168 W14 P2-10), use "
    "extensions.core_entities.users.domain.models instead. "
    "Will be removed в S169+.",
    DeprecationWarning,
    stacklevel=2,
)

__all__ = ("User", "_get_password_hasher", "argon2_exceptions")
