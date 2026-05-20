"""Protocol для batch inference backend'ов (S13 K4 W2).

Поддерживает 2 production-ready реализации:

* :class:`VllmBatchClient` — self-hosted vLLM (GPU);
* :class:`TgiBatchClient` — HuggingFace TGI HTTP-сервер (через WAF).
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

__all__ = ("BatchInferenceClient",)


@runtime_checkable
class BatchInferenceClient(Protocol):
    """Контракт batch inference (completion + embedding)."""

    async def batch_completions(
        self,
        prompts: list[str],
        *,
        model: str,
        max_tokens: int = 256,
        temperature: float = 0.0,
    ) -> list[str]:
        """Сгенерировать N completions параллельно.

        Args:
            prompts: Входные prompts.
            model: Имя модели.
            max_tokens: Лимит токенов на ответ.
            temperature: Sampling temperature.

        Returns:
            Список completions в исходном порядке.
        """
        ...

    async def batch_embeddings(
        self, texts: list[str], *, model: str
    ) -> list[list[float]]:
        """Вычислить embeddings для N текстов.

        Args:
            texts: Входные тексты.
            model: Имя embedding-модели.

        Returns:
            Список векторов в исходном порядке.
        """
        ...
