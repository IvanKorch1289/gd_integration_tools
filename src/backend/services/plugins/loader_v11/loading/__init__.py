from __future__ import annotations

"""LoadingMixin package (S63 W1 decomp from loading.py 496 LOC).

5 methods decomposed в 2 mixin files + state.py:
- ``loader_mixin.py`` (2): _load_one (BIG 253 LOC), _instantiate
- ``frontend_mixin.py`` (3): _mount_frontend_pages, _unmount_frontend_pages, _plugin_page_prefix
- ``state.py``: PluginInventoryConflictError, LoadedPluginV11

No core methods.

Backward-compat: ``from src.backend.services.plugins.loader_v11.loading import LoadingMixin`` works.
"""


from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    pass

from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Callable

    from src.backend.core.interfaces.plugin import (
        ActionRegistryProtocol,
        BasePlugin,
        ProcessorRegistryProtocol,
        RepositoryRegistryProtocol,
    )
    from src.backend.core.security.capabilities import CapabilityGate
    from src.backend.services.plugins.loader_v11 import (
        LoadedPluginV11 as _LoadedPluginV11,
    )
    from src.backend.services.plugins.manifest_v11 import PluginManifestV11

# Note: LoadedPluginV11 is also defined locally below (S52 W3 leftover from original imports_block)

import importlib
from dataclasses import dataclass

from src.backend.core.interfaces.plugin import BasePlugin, PluginContext
from src.backend.core.logging import get_logger
from src.backend.core.plugin_runtime.compat_checker import CompatViolation
from src.backend.core.security.capabilities import CapabilityError, CapabilityRef
from src.backend.services.plugins.manifest_v11 import (
    PluginManifestError,
    PluginManifestV11,
    load_plugin_manifest,
)

_logger = get_logger("services.plugins.loader_v11")

from src.backend.services.plugins.loader_v11.loading.frontend_mixin import (
    FrontendMixin,  # S63 W1: MRO
)
from src.backend.services.plugins.loader_v11.loading.loader_mixin import (
    LoaderMixin,  # S63 W1: MRO
)
from src.backend.services.plugins.loader_v11.loading.state import (
    LoadedPluginV11,  # S63 W1: re-export
    PluginInventoryConflictError,  # S63 W1: re-export
)

__all__ = ("LoadingMixin", "PluginInventoryConflictError", "LoadedPluginV11")


class LoadingMixin(LoaderMixin, FrontendMixin):
    """Plugin loading mixin (2 mixins = 5 methods, no core)."""

    __slots__ = ()
