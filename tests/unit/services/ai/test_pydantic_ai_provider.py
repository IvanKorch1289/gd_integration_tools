"""TDD: PydanticAI provider wrapper (S171 M28, D295).

Pattern (D295, Ponytail): thin wrapper, no abstractions.
"""
# ruff: noqa: S101
from __future__ import annotations


class TestPydanticAIProvider:
    def test_instantiates(self) -> None:
        from src.backend.services.ai.agents_pydantic.base import ModelSpec
        # M2.1: ModelSpec API drift — был (name=, model=), сейчас
        # (model_name: str, system_prompt_override: str | None).
        agent = ModelSpec(
            model_name="gpt-4",
            system_prompt_override="You are test_agent",
        )
        assert agent.model_name == "gpt-4"
        assert agent.system_prompt_override == "You are test_agent"

    def test_adapter_importable(self) -> None:
        # M2.1: adapter.py экспортирует LiteLLMModel (pydantic-ai Model impl),
        # не ModelSpec (который экспортируется из base.py).
        from src.backend.services.ai.agents_pydantic.adapter import LiteLLMModel
        assert LiteLLMModel is not None
        assert hasattr(LiteLLMModel, "request")
