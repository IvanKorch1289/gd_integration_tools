"""Capability-checked facade для plugin manifest (S120 W1, Cycle 47).

ADR-0207 + Cycle 47 fix: extensions/* и internal callers импортируют
``PluginManifest`` из ``services.plugins.manifest_toml``. V22 boundary
требует, чтобы extensions имели доступ ТОЛЬКО к ``core.*`` + фасадам.

Этот модуль — thin re-export, который легитимизирует cross-layer access
для plugin authoring / testing use-cases.

Cycle 47: re-export source migrated from
``services.plugins.manifest_toml`` to the canonical
``core.plugin_runtime.manifest_toml`` (which contains identical
content). This fixes the layer-boundary violation noted by the
Layer 3 re-analyzer (cycle 42): ``core.*`` no longer imports
``services.*``.

Out of scope: 28 internal callers in ``services/plugins/loader/*``
still import from ``services.plugins.manifest_toml``. Migration
tracked as backlog (large refactor, no behavior change).

Migration path:
- ``from src.backend.services.plugins.manifest_toml import load_plugin_manifest``
  → ``from src.backend.core.plugin_runtime.manifest import load_plugin_manifest``

Related:
- AGENTS.md (boundary rules)
- ADR-0207 (S120 W5 closure)
- ADR-042 (V11 plugin manifest)
"""

from __future__ import annotations

# Cycle 47: import from canonical core location, not services.
# This fixes core→services boundary violation (Layer 3 re-analyzer finding).
from src.backend.core.plugin_runtime.manifest_toml import (  # noqa: F401
    PluginCompatibility,
    PluginManifest,
    PluginManifestError,
    PluginProvides,
    PluginSandbox,
    PluginTenantDecl,
    load_plugin_manifest,
)

__all__ = (
    "PluginCompatibility",
    "PluginManifestError",
    "PluginManifest",
    "PluginProvides",
    "PluginSandbox",
    "PluginTenantDecl",
    "load_plugin_manifest",
)
