"""AI/ML infrastructure: semantic_cache, vector_store.

Wave 0.11: ``PromptRegistry`` живёт в ``src.services.ai.prompt_registry``
(Langfuse-backed). In-memory stub из infrastructure удалён — больше нет
дублирования.
"""

from src.infrastructure.ai.semantic_cache import SemanticCache

__all__ = ("SemanticCache",)
