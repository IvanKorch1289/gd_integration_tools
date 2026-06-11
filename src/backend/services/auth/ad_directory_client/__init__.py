from __future__ import annotations
"""AD directory client package (S67 W4 decomp from ad_directory_client.py 457 LOC).

4 classes -> 2 files (per-concern):
- ``state.py``: AdAuthError + AdServerConfig + AdSearchEntry (3 data classes)
- ``client.py``: AdDirectoryClient (7 methods)

Backward-compat: ``from src.backend.services.auth.ad_directory_client import AdDirectoryClient`` works.
"""


from src.backend.services.auth.ad_directory_client.state import AdAuthError  # S67 W4: re-export
from src.backend.services.auth.ad_directory_client.state import AdServerConfig  # S67 W4: re-export
from src.backend.services.auth.ad_directory_client.state import AdSearchEntry  # S67 W4: re-export
from src.backend.services.auth.ad_directory_client.client import AdDirectoryClient  # S67 W4: re-export

__all__ = (
    "AdAuthError",
    "AdServerConfig",
    "AdSearchEntry",
    "AdDirectoryClient",
)
