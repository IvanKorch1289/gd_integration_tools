"""Wave 4 (Roadmap V10) — composition root для plugin-системы.

Слой `services/plugins/` склеивает `core/interfaces/plugin.py` (контракт)
с конкретными реестрами actions/processors/repository-hooks и
обнаружением плагинов через `importlib.metadata.entry_points`.

Публичные точки входа:

* :class:`PluginLoader` — orchestrator (discovery + lifecycle).
* :class:`RepositoryHookRegistry` — централизованный реестр hooks/override.
* :func:`repository_hook` / :func:`override_method` — декораторы.
* :class:`PluginManifest` — pydantic-схема `plugin.yaml`.
"""

from __future__ import annotations

from src.services.plugins.decorators import override_method, repository_hook
from src.services.plugins.loader import PluginLoader, get_plugin_loader
from src.services.plugins.manifest import PluginManifest, load_manifest
from src.services.plugins.registries import (
    ActionRegistryAdapter,
    ProcessorRegistryAdapter,
    RepositoryHookRegistry,
    get_repository_hook_registry,
)

__all__ = (
    "ActionRegistryAdapter",
    "PluginLoader",
    "PluginManifest",
    "ProcessorRegistryAdapter",
    "RepositoryHookRegistry",
    "get_plugin_loader",
    "get_repository_hook_registry",
    "load_manifest",
    "override_method",
    "repository_hook",
)
