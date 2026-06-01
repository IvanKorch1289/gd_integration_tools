"""Image-generation сервисы К4 S7 (LiteLLM-обёртка).

Реализуют:
    * :class:`LiteLLMImageGenerationService` — async-wrapper над
      ``litellm.image_generation()`` (DALL·E / Stable Diffusion / Gemini).

Активация: feature_flag ``voice_image_gen_enabled`` (default-OFF).
Capability (V11.1): ``image.generate.<provider>``.
Cost tracking: через :mod:`services.ai.metrics.AgentMetricsService`
(record_cost) — best-effort, не ломает вызов.
"""

from src.backend.services.ai.image_generation.litellm_image import (
    ImageGenerationUnavailable,
    ImageResult,
    LiteLLMImageGenerationService,
)

__all__ = ("ImageGenerationUnavailable", "ImageResult", "LiteLLMImageGenerationService")
