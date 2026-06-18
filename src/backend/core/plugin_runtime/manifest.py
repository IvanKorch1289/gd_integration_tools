"""Capability-checked facade для plugin manifest (S120 W1).

ADR-0207: extensions/* tests импортируют ``load_plugin_manifest`` и
``PluginManifest`` из ``services.plugins.manifest_toml``. V22 boundary
требует, чтобы extensions имели доступ ТОЛЬКО к ``core.*`` + фасадам.

Этот модуль — thin re-export, который легитимизирует cross-layer access
для plugin authoring / testing use-cases.

Migration path:
- ``from src.backend.services.plugins.manifest_toml import load_plugin_manifest``
  → ``from src.backend.core.plugin_runtime.manifest import load_plugin_manifest``

Related:
- AGENTS.md (boundary rules)
- ADR-0207 (S120 W5 closure)
- ADR-042 (V11 plugin manifest)
"""

from __future__ import annotations

from src.backend.services.plugins.manifest_toml import (  # noqa: F401
    PluginCompatibility,
    PluginManifestError,
    PluginManifest,
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
