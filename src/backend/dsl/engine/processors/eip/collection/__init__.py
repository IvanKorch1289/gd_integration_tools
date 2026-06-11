"""Collection EIP processors package (S57 W3 decomp from collection.py 569 LOC).

13 processor classes + 1 helper decomposed в 4 files (per collection concept):
- ``collect.py``: CollectProcessor, FindAllProcessor, GroupByProcessor + _resolve_field
- ``partition.py``: PartitionProcessor, OrElseProcessor, FlattenProcessor, UniqueProcessor
- ``set_ops.py``: IntersectProcessor, DiffProcessor
- ``aggregators.py``: SumByProcessor, MaxByProcessor, MinByProcessor, SortByProcessor

Backward-compat: ``from src.backend.dsl.engine.processors.eip.collection import CollectProcessor`` works.
"""

from __future__ import annotations

from src.backend.dsl.engine.processors.eip.collection.aggregators import (
    MaxByProcessor,  # S57 W3: re-export
    MinByProcessor,  # S57 W3: re-export
    SortByProcessor,  # S57 W3: re-export
    SumByProcessor,  # S57 W3: re-export
)
from src.backend.dsl.engine.processors.eip.collection.collect import (
    CollectProcessor,  # S57 W3: re-export
    FindAllProcessor,  # S57 W3: re-export
    GroupByProcessor,  # S57 W3: re-export
    _resolve_field,  # S57 W3: re-export
)
from src.backend.dsl.engine.processors.eip.collection.partition import (
    FlattenProcessor,  # S57 W3: re-export
    OrElseProcessor,  # S57 W3: re-export
    PartitionProcessor,  # S57 W3: re-export
    UniqueProcessor,  # S57 W3: re-export
)
from src.backend.dsl.engine.processors.eip.collection.set_ops import (
    DiffProcessor,  # S57 W3: re-export
    IntersectProcessor,  # S57 W3: re-export
)

__all__ = (
    "CollectProcessor",
    "FindAllProcessor",
    "GroupByProcessor",
    "PartitionProcessor",
    "OrElseProcessor",
    "FlattenProcessor",
    "UniqueProcessor",
    "IntersectProcessor",
    "DiffProcessor",
    "SumByProcessor",
    "MaxByProcessor",
    "MinByProcessor",
    "SortByProcessor",
    "_resolve_field",
)
