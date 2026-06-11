"""Database package (S64 W3 decomp from database.py 489 LOC).

3 classes + 4 funcs → 4 files (per concern):
- ``bundle.py``: DatabaseBundle
- ``initializer.py``: DatabaseInitializer (13 methods)
- ``registry.py``: ExternalDatabaseRegistry (7 methods)
- ``accessors.py``: 4 top-level funcs (get_db_initializer, get_smart_session_manager, get_external_db_registry, __getattr__)

Backward-compat: ``from src.backend.infrastructure.database.database import DatabaseInitializer`` works.
"""

from __future__ import annotations

from src.backend.infrastructure.database.database.accessors import (
    __getattr__,  # S64 W3: accessor re-export
    get_db_initializer,  # S64 W3: accessor re-export
    get_external_db_registry,  # S64 W3: accessor re-export
    get_smart_session_manager,  # S64 W3: accessor re-export
)
from src.backend.infrastructure.database.database.bundle import (
    DatabaseBundle,  # S64 W3: re-export
)
from src.backend.infrastructure.database.database.initializer import (
    DatabaseInitializer,  # S64 W3: re-export
)
from src.backend.infrastructure.database.database.registry import (
    ExternalDatabaseRegistry,  # S64 W3: re-export
)

__all__ = (
    "DatabaseBundle",
    "DatabaseInitializer",
    "ExternalDatabaseRegistry",
    "get_db_initializer",
    "get_smart_session_manager",
    "get_external_db_registry",
    "__getattr__",
)
