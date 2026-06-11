from __future__ import annotations

"""CDC client package (S60 W2 decomp from cdc.py 538 LOC).

7 classes + 1 helper decomposed в 3 files (per concern):
- ``events.py``: CDCEvent, CDCSubscription (data classes)
- ``strategies.py``: _CDCStrategy (base) + _PollingStrategy + _ListenNotifyStrategy + _LogMinerStrategy
- ``client.py``: CDCClient (main client) + 1 top-level helper

Backward-compat: ``from src.backend.infrastructure.clients.external.cdc import CDCClient`` works.
"""


from src.backend.infrastructure.clients.external.cdc.client import (
    CDCClient,  # S60 W2: re-export
    get_cdc_client,  # S60 W2: helper re-export
)
from src.backend.infrastructure.clients.external.cdc.events import (
    CDCEvent,  # S60 W2: re-export
    CDCSubscription,  # S60 W2: re-export
)
from src.backend.infrastructure.clients.external.cdc.strategies import (
    _CDCStrategy,  # S60 W2: re-export
    _ListenNotifyStrategy,  # S60 W2: re-export
    _LogMinerStrategy,  # S60 W2: re-export
    _PollingStrategy,  # S60 W2: re-export
)

__all__ = (
    "CDCEvent",
    "CDCSubscription",
    "_CDCStrategy",
    "_PollingStrategy",
    "_ListenNotifyStrategy",
    "_LogMinerStrategy",
    "CDCClient",
    "get_cdc_client",
)
