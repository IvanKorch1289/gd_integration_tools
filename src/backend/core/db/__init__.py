"""Backward-compat namespace package.

S169: ``core/db/`` merged into ``core/database/``.
All content moved to ``src.backend.core.database``.
This package exists solely for backward compatibility.

Backward-compat re-exports:
- ``src.backend.core.db.external_facade`` → re-exports from
  ``src.backend.core.database.external_facade``

New code should import directly from ``src.backend.core.database.*``.
"""

from src.backend.core.database import (
    dialect_types,
    external_facade,
    initializer,
    session,
)

__all__ = ["dialect_types", "external_facade", "initializer", "session"]
