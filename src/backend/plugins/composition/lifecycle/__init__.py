"""lifecycle - application lifespan + bootstrap (S66 W3 decomp).

lifespan() 538 LOC extracted to lifespan.py. __init__.py is now thin re-exports.

Sibling S82 already extracted: protocols (W1), bootstrap (W2), v11 (W3), watchers (W4).
S66 W3: lifespan -> lifespan.py.
"""

from __future__ import annotations

from src.backend.plugins.composition.lifecycle import (  # noqa: F401
    bootstrap,
    plugin_loader,  # S168 W15-17: renamed from v11.py → plugin_loader.py
    protocols,
    shutdown,
    signals,
    startup,
    watchers,
)
from src.backend.plugins.composition.lifecycle import lifespan as lifespan_module
from src.backend.plugins.composition.lifecycle.bootstrap import (  # noqa: E402, F401
    bootstrap_resilience_coordinator,
    bootstrap_snapshot_job,
    register_storage_singletons,
    validate_cache_layers,
)
from src.backend.plugins.composition.lifecycle.lifespan import (
    get_task_registry,  # noqa: E402, F401
    lifespan,
)

__all__ = (
    "lifespan",
    "register_storage_singletons",
    "validate_cache_layers",
    "bootstrap_snapshot_job",
    "bootstrap_resilience_coordinator",
    "get_task_registry",
    "bootstrap",
    "lifespan_module",
    "plugin_loader",  # S168 W15-17: was v11
    "protocols",
    "shutdown",
    "signals",
    "startup",
    "watchers",
)
