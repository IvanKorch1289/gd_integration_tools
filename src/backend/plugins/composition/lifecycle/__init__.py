"""lifecycle - application lifespan + bootstrap (S66 W3 decomp).

lifespan() 538 LOC extracted to lifespan.py. __init__.py is now thin re-exports.

Sibling S82 already extracted: protocols (W1), bootstrap (W2), v11 (W3), watchers (W4).
S66 W3: lifespan -> lifespan.py.
"""

from __future__ import annotations

from src.backend.plugins.composition.lifecycle import (
    bootstrap,
    plugin_loader,  # S168 W15-17: renamed from v11.py → plugin_loader.py
    protocols,
    shutdown,
    signals,
    startup,
    watchers,
)
from src.backend.plugins.composition.lifecycle import (
    lifespan as lifespan_module,  # noqa: F401 — re-export
)
from src.backend.plugins.composition.lifecycle.bootstrap import (
    bootstrap_resilience_coordinator,
    bootstrap_snapshot_job,
    register_storage_singletons,
    validate_cache_layers,
)
from src.backend.plugins.composition.lifecycle.lifespan import (
    get_task_registry,
    lifespan,
)

__all__ = (
    "bootstrap",
    "bootstrap_resilience_coordinator",
    "bootstrap_snapshot_job",
    "get_task_registry",
    "lifespan",
    "lifespan_module",
    "plugin_loader",  # S168 W15-17: was v11
    "protocols",
    "register_storage_singletons",
    "shutdown",
    "signals",
    "startup",
    "validate_cache_layers",
    "watchers",
)
