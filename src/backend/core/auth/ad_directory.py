"""Capability-checked facade для AD directory client (S124 W1).

ADR-0207: extensions/core_entities/users/services/users.py импортирует
``AdAuthError`` и ``AdSearchEntry`` из
``services.auth.ad_directory_client`` (sub-package).
"""

from __future__ import annotations

from src.backend.services.auth.ad_directory_client import (  # noqa: F401
    AdAuthError,
    AdSearchEntry,
)

__all__ = ("AdAuthError", "AdSearchEntry")
