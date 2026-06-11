"""lifecycle - application lifespan + bootstrap (S66 W3 decomp).

lifespan() 538 LOC extracted to lifespan.py. __init__.py is now thin re-exports.

Sibling S82 already extracted: protocols (W1), bootstrap (W2), v11 (W3), watchers (W4).
S66 W3: lifespan -> lifespan.py.
"""

from __future__ import annotations

from src.backend.plugins.composition.lifecycle.bootstrap import (  # noqa: E402, F401
    bootstrap_resilience_coordinator,
    bootstrap_snapshot_job,
    register_storage_singletons,
    validate_cache_layers,
)
from src.backend.plugins.composition.lifecycle.lifespan import (
    lifespan,  # noqa: E402, F401
)

__all__ = (
    "lifespan",
    "register_storage_singletons",
    "validate_cache_layers",
    "bootstrap_snapshot_job",
    "bootstrap_resilience_coordinator",
)
