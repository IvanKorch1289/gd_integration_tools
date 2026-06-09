"""vLLM batch inference client (S13 K4 W2).

Self-hosted GPU-accelerated inference через ``vllm.AsyncEngine``.
Capability: ``ai.batch_inference.vllm:internal`` (без WAF).

Lazy import vllm — heavy CUDA-зависимость в ``[ai-batch]`` extra.
"""

from __future__ import annotations

from typing import Any

from src.backend.core.logging import get_logger

__all__ = ("VllmBatchClient",)

logger = get_logger(__name__)


class VllmBatchClient:
    """vLLM AsyncEngine wrapper для batch inference."""

    def __init__(
        self, *, engine: Any | None = None, model_name: str | None = None
    ) -> None:
        """Args:
        engine: Готовый ``vllm.AsyncEngine`` (для тестов/DI).
        model_name: Если engine не передан — лениво создать с этой моделью.
        """
        self._engine = engine
        self._model_name = model_name

    async def _ensure_engine(self) -> Any:
        if self._engine is not None:
            return self._engine
        from vllm import AsyncEngineArgs, AsyncLLMEngine

        engine_args = AsyncEngineArgs(model=self._model_name or "facebook/opt-125m")
        self._engine = AsyncLLMEngine.from_engine_args(engine_args)
        return self._engine

    async def batch_completions(
        self,
        prompts: list[str],
        *,
        model: str,
        max_tokens: int = 256,
        temperature: float = 0.0,
    ) -> list[str]:
        from vllm import SamplingParams

        engine = await self._ensure_engine()
        sampling = SamplingParams(temperature=temperature, max_tokens=max_tokens)
        results: list[str] = []
        for i, prompt in enumerate(prompts):
            request_id = f"batch-{i}"
            async for output in engine.generate(prompt, sampling, request_id):
                if output.finished:
                    results.append(output.outputs[0].text)
                    break
        return results

    async def batch_embeddings(
        self, texts: list[str], *, model: str
    ) -> list[list[float]]:
        # vLLM поддерживает embeddings только в специфичных версиях; в общем
        # случае рекомендуется использовать SentenceTransformers/TGI.
        raise NotImplementedError(
            "vLLM batch_embeddings: используйте TgiBatchClient или "
            "SentenceTransformers для embedding workload"
        )
