"""SAML package (Sprint 9 K1 W1).

Расширение flat-модуля :mod:`src.backend.core.auth.saml_backend` до пакета
с разделением:

* :mod:`saml_backend` — низкоуровневый класс :class:`SamlBackend` (S6 K1 W1);
* :mod:`sp_handler` — высокоуровневый orchestrator SP-initiated SSO flow
  (login redirect + ACS endpoint helpers, Sprint 9).

Re-export для backwards-compat: импорт ``from src.backend.core.auth.saml import
SamlBackend`` работает наравне с историческим ``saml_backend`` модулем.
"""

from __future__ import annotations

from src.backend.core.auth.saml_backend import (
    IdpMetadata,
    SamlAuthResult,
    SamlBackend,
    SamlConfig,
    SamlError,
)
from src.backend.core.auth.saml.sp_handler import (
    SamlSpHandler,
    SpInitiatedLoginResult,
)

__all__ = (
    "IdpMetadata",
    "SamlAuthResult",
    "SamlBackend",
    "SamlConfig",
    "SamlError",
    "SamlSpHandler",
    "SpInitiatedLoginResult",
)
