# ruff: noqa: S101
"""Unit tests for PromptRegistry (services/ai/prompt_registry.py)."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock

import pytest

from src.backend.services.ai.prompt_registry import (
    PromptRegistry,
    PromptVersion,
    get_prompt_registry,
)


@pytest.fixture(autouse=True)
def _reset_singleton() -> Any:
    """Сбрасывает singleton перед каждым тестом."""
    import src.backend.services.ai.prompt_registry as _mod

    _mod._instance = None
    yield
    _mod._instance = None


# ── fallback register / get ─────────────────────────────────────


@pytest.mark.asyncio
async def test_register_and_get_fallback() -> None:
    reg = PromptRegistry()
    reg.register("greet", template="Hello, {name}!")
    pv = await reg.get("greet", variables={"name": "World"})
    assert isinstance(pv, PromptVersion)
    assert pv.compiled == "Hello, World!"
    assert pv.name == "greet"
    assert pv.version == 1
    assert pv.labels == {"source": "fallback"}


@pytest.mark.asyncio
async def test_register_with_version_and_labels() -> None:
    reg = PromptRegistry()
    reg.register("greet", template="Hi {name}", version=2, labels={"lang": "en"})
    pv = await reg.get("greet", version=2)
    assert pv.version == 2
    assert pv.labels == {"lang": "en"}


@pytest.mark.asyncio
async def test_get_latest_version_by_default() -> None:
    reg = PromptRegistry()
    reg.register("q", template="v1", version=1)
    reg.register("q", template="v2", version=2)
    pv = await reg.get("q")
    assert pv.version == 2
    assert pv.compiled == "v2"


@pytest.mark.asyncio
async def test_get_async_compiles_with_variables() -> None:
    reg = PromptRegistry()
    reg.register("qa", template="Q: {q}\nA:")
    pv = await reg.get("qa", variables={"q": "What is AI?"})
    assert pv.compiled == "Q: What is AI?\nA:"


# ── missing variable handling ───────────────────────────────────


@pytest.mark.asyncio
async def test_get_uses_template_when_variable_missing() -> None:
    reg = PromptRegistry()
    reg.register("qa", template="Q: {q}\nA:")
    pv = await reg.get("qa", variables={})
    assert pv.compiled == "Q: {q}\nA:"


# ── key error on unknown prompt ─────────────────────────────────


@pytest.mark.asyncio
async def test_get_raises_when_prompt_not_found() -> None:
    reg = PromptRegistry()
    with pytest.raises(KeyError, match="not found in registry"):
        await reg.get("unknown")


# ── langfuse path ───────────────────────────────────────────────


@pytest.mark.asyncio
async def test_langfuse_path_compiles_and_returns_version() -> None:
    reg = PromptRegistry()
    mock_lf = MagicMock()
    mock_prompt = MagicMock()
    mock_prompt.compile.return_value = "compiled text"
    mock_prompt.version = 5
    mock_prompt.prompt = "template text"
    mock_lf.get_prompt.return_value = mock_prompt
    reg._langfuse = mock_lf

    pv = await reg.get("my_prompt", variables={"x": 1})
    assert pv.compiled == "compiled text"
    assert pv.version == 5
    assert pv.labels["source"] == "langfuse"
    mock_lf.get_prompt.assert_called_once_with(
        "my_prompt", label="production", version=None
    )


@pytest.mark.asyncio
async def test_langfuse_path_compile_raises_uses_fallback() -> None:
    reg = PromptRegistry()
    mock_lf = MagicMock()
    mock_prompt = MagicMock()
    mock_prompt.compile.side_effect = RuntimeError("compile err")
    mock_prompt.version = 3
    mock_prompt.prompt = "tpl"
    mock_lf.get_prompt.return_value = mock_prompt
    reg._langfuse = mock_lf
    reg.register("p", template="fallback {x}")

    pv = await reg.get("p", variables={"x": "ok"})
    assert pv.compiled == "fallback ok"
    assert pv.labels["source"] == "fallback"


@pytest.mark.asyncio
async def test_langfuse_fallback_on_exception() -> None:
    reg = PromptRegistry()
    mock_lf = MagicMock()
    mock_lf.get_prompt.side_effect = RuntimeError("down")
    reg._langfuse = mock_lf
    reg.register("p", template="fallback {x}")

    pv = await reg.get("p", variables={"x": "ok"})
    assert pv.compiled == "fallback ok"
    assert pv.labels["source"] == "fallback"


# ── singleton ───────────────────────────────────────────────────


def test_get_prompt_registry_singleton() -> None:
    r1 = get_prompt_registry()
    r2 = get_prompt_registry()
    assert r1 is r2
