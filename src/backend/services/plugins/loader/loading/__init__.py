"""LoadingMixin package (S63 W1 decomp from loading.py 496 LOC).

5 methods decomposed в 2 mixin files + state.py:
- ``loader_mixin.py`` (2): _load_one (BIG 253 LOC), _instantiate
- ``frontend_mixin.py`` (3): _mount_frontend_pages, _unmount_frontend_pages, _plugin_page_prefix
- ``state.py``: PluginInventoryConflictError, LoadedPlugin

No core methods.

Backward-compat: ``from src.backend.services.plugins.loader.loading import LoadingMixin`` works.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    pass

from src.backend.core.logging import get_logger

_logger = get_logger("services.plugins.loader")

from src.backend.services.plugins.loader.loading.frontend_mixin import (
    FrontendMixin,  # S63 W1: MRO
)
from src.backend.services.plugins.loader.loading.loader_mixin import (
    LoaderMixin,  # S63 W1: MRO
)
from src.backend.services.plugins.loader.loading.state import (
    LoadedPlugin,  # S63 W1: re-export
    PluginInventoryConflictError,  # S63 W1: re-export
)

__all__ = ("LoadingMixin", "PluginInventoryConflictError", "LoadedPlugin")


class LoadingMixin(LoaderMixin, FrontendMixin):
    """Plugin loading mixin (2 mixins = 5 methods, no core)."""

    __slots__ = ()
