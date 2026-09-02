"""Unit-тесты ``services.ai.image_generation`` — coverage ratchet (Post-Plan A Sprint 15).

core/ai/image_generation service package facade (K4 S7 + V11.1):
re-exports 3 symbols (ImageGenerationUnavailable, ImageResult,
LiteLLMImageGenerationService). ~6 stmts, 0% coverage.

Цель slice: 0% → 100% через __all__ audit + class identity.
"""

from __future__ import annotations

import pytest

from src.backend.services.ai import image_generation
from src.backend.services.ai.image_generation import (
    ImageGenerationUnavailable,
    ImageResult,
    LiteLLMImageGenerationService,
)


@pytest.mark.unit
class TestImageGenerationFacadeAllExports:
    """``__all__`` audit + class identity."""

    @pytest.mark.parametrize(
        "symbol_name",
        [
            "ImageGenerationUnavailable",
            "ImageResult",
            "LiteLLMImageGenerationService",
        ],
    )
    def test_all_exports_accessible(self, symbol_name: str) -> None:
        """Каждый символ из ``__all__`` доступен через facade."""
        assert hasattr(image_generation, symbol_name), (
            f"Missing export: {symbol_name}"
        )
        assert symbol_name in image_generation.__all__, (
            f"{symbol_name} not declared in __all__"
        )

    def test_all_declared_count(self) -> None:
        """``__all__`` содержит 3 символа."""
        assert len(image_generation.__all__) == 3

    def test_module_docstring_present(self) -> None:
        """Module docstring описывает image generation (K4 S7 + V11.1)."""
        assert image_generation.__doc__ is not None
        assert "image" in image_generation.__doc__.lower() or "LiteLLM" in image_generation.__doc__


@pytest.mark.unit
class TestImageGenerationFacadeIdentity:
    """Identity checks для 3 re-exports."""

    def test_litellm_image_generation_service_is_class(self) -> None:
        """``LiteLLMImageGenerationService`` — class (LiteLLM wrapper)."""
        assert isinstance(LiteLLMImageGenerationService, type)

    def test_image_result_is_class(self) -> None:
        """``ImageResult`` — class (result dataclass)."""
        assert isinstance(ImageResult, type)

    def test_image_generation_unavailable_is_exception(self) -> None:
        """``ImageGenerationUnavailable`` — Exception subclass."""
        assert isinstance(ImageGenerationUnavailable, type)
        assert issubclass(ImageGenerationUnavailable, Exception)
