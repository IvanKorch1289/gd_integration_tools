"""Unit-тесты ``services.ai.prompts`` — coverage ratchet (S49 W11).

services/ai/prompts/__init__.py — prompt storage facade: re-exports
LangfusePromptStorage + PromptEntry + get_prompt_storage. 12 statements,
0% coverage.

Цель slice: 0% → 100% через __all__ audit + class/callable identity.
"""

from __future__ import annotations

import pytest

from src.backend.services.ai import prompts
from src.backend.services.ai.prompts import (
    LangfusePromptStorage,
    PromptEntry,
    get_prompt_storage,
)


@pytest.mark.unit
class TestPromptsFacadeAllExports:
    """``__all__`` audit + class/callable identity."""

    @pytest.mark.parametrize(
        "symbol_name",
        ["LangfusePromptStorage", "PromptEntry", "get_prompt_storage"],
    )
    def test_all_exports_accessible(self, symbol_name: str) -> None:
        """Каждый символ из ``__all__`` доступен через facade."""
        assert hasattr(prompts, symbol_name), (
            f"Missing export: {symbol_name}"
        )
        assert symbol_name in prompts.__all__, (
            f"{symbol_name} not declared in __all__"
        )

    def test_all_declared_count(self) -> None:
        """``__all__`` содержит 3 символа."""
        assert len(prompts.__all__) == 3

    def test_module_docstring_present(self) -> None:
        """Module docstring описывает prompt storage (Langfuse SDK)."""
        assert prompts.__doc__ is not None
        assert "prompt" in prompts.__doc__.lower() or "Langfuse" in prompts.__doc__


@pytest.mark.unit
class TestPromptsFacadeIdentity:
    """Identity checks для re-exports."""

    def test_langfuse_prompt_storage_is_class(self) -> None:
        """``LangfusePromptStorage`` — class (storage backend)."""
        assert isinstance(LangfusePromptStorage, type)

    def test_prompt_entry_is_class(self) -> None:
        """``PromptEntry`` — class (dataclass / pydantic model)."""
        assert isinstance(PromptEntry, type)

    def test_get_prompt_storage_is_callable(self) -> None:
        """``get_prompt_storage`` — callable (factory)."""
        assert callable(get_prompt_storage)
