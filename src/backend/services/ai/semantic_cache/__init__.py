"""Semantic cache package (S67 W3 decomp from semantic_cache.py 461 LOC).

2 classes + 2 funcs -> 3 files (per-class):
- ``semantic_cache.py``: SemanticCache (8 methods)
- ``l3_cache.py``: L3RetrievalGraphCache (10 methods)
- ``helpers.py``: 2 module-level funcs

Backward-compat: ``from src.backend.services.ai.semantic_cache import SemanticCache`` works.
"""

from __future__ import annotations

from src.backend.services.ai.semantic_cache.helpers import (
    get_l3_retrieval_cache,  # S67 W3: helper re-export
    get_semantic_cache,  # S67 W3: helper re-export
)
from src.backend.services.ai.semantic_cache.l3_cache import (
    RAG_CACHE_INVALIDATE_CHANNEL,  # S124 W2: re-export for test_l3_retrieval
    L3RetrievalGraphCache,  # S67 W3: re-export
)
from src.backend.services.ai.semantic_cache.semantic_cache import (
    SemanticCache,  # S67 W3: re-export
)

__all__ = (
    "SemanticCache",
    "L3RetrievalGraphCache",
    "RAG_CACHE_INVALIDATE_CHANNEL",
    "get_semantic_cache",
    "get_l3_retrieval_cache",
)
