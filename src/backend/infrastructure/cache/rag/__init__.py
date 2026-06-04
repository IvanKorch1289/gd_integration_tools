"""3-tier RAG cache (К4 MVP, Шаг 2).

* :class:`L1ExactCache` — exact KV-кэш по hash(query) (Redis).
* :class:`L2SemanticRagCache` — semantic-кэш по эмбеддингам (Qdrant).
* :class:`L3RetrievalCache` — кэш сырых retrieval-чанков (Redis).
* :class:`ThreeTierRagCache` — фасад: lookup L1 → L2 → L3 + store.
* :class:`RagInvalidationBus` — pub/sub-канал для invalidate_by_tag.

Изолированный пакет: НЕ пересекается со старыми ``infrastructure/cache/``
и ``services/ai/semantic_cache.py``. Sprint 4/5 будут наращивать поверх.
"""

from src.backend.infrastructure.cache.rag.exact import L1ExactCache
from src.backend.infrastructure.cache.rag.invalidation import RagInvalidationBus
from src.backend.infrastructure.cache.rag.metrics import record_hit, record_miss
from src.backend.infrastructure.cache.rag.retrieval import L3RetrievalCache
from src.backend.infrastructure.cache.rag.semantic import L2SemanticRagCache
from src.backend.infrastructure.cache.rag.three_tier import ThreeTierRagCache

__all__ = (
    "L1ExactCache",
    "L2SemanticRagCache",
    "L3RetrievalCache",
    "RagInvalidationBus",
    "ThreeTierRagCache",
    "record_hit",
    "record_miss",
)
