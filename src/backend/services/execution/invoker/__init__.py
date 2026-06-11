from __future__ import annotations

"""Invoker package (S68 W3 decomp from invoker/__init__.py 446 LOC).

2 classes + 7 funcs -> 3 files (per-concern):
- ``types.py``: InvocationMode (enum-like)
- ``invoker.py``: Invoker (5 methods)
- ``helpers.py``: 7 module-level funcs (incl. _serialize/_deserialize duplicates)

Backward-compat: ``from src.backend.services.execution.invoker import Invoker`` works.
"""


from src.backend.services.execution.invoker.helpers import (
    _deserialize_request,  # S68 W3: helper re-export
    _is_async_iterator,  # S68 W3: helper re-export
    _run_deferred_job,  # S68 W3: helper re-export
    _serialize_request,  # S68 W3: helper re-export
    get_invoker,  # S68 W3: helper re-export
)
from src.backend.services.execution.invoker.invoker import Invoker  # S68 W3: re-export
from src.backend.services.execution.invoker.types import (
    InvocationMode,  # S68 W3: re-export
)

__all__ = (
    "InvocationMode",
    "Invoker",
    "_is_async_iterator",
    "_serialize_request",
    "_deserialize_request",
    "_run_deferred_job",
    "get_invoker",
)
