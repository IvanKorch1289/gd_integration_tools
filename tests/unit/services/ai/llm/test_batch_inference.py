"""Unit-тесты BatchInferenceProtocol + TgiBatchClient + VllmBatchClient (S13 K4 W2)."""

# ruff: noqa: S101

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.backend.services.ai.llm.batch_inference_protocol import BatchInferenceClient
from src.backend.services.ai.llm.tgi_batch_client import TgiBatchClient
from src.backend.services.ai.llm.vllm_batch_client import VllmBatchClient


def test_protocol_is_runtime_checkable() -> None:
    """TgiBatchClient and VllmBatchClient implement BatchInferenceClient."""

    # Создаём минимальные экземпляры.
    tgi = TgiBatchClient(base_url="http://tgi:80", http_client=MagicMock())
    vllm = VllmBatchClient(engine=MagicMock())
    # isinstance protocol check.
    assert isinstance(tgi, BatchInferenceClient)
    assert isinstance(vllm, BatchInferenceClient)


@pytest.mark.asyncio
async def test_tgi_batch_completions_parallel() -> None:
    http = AsyncMock()
    response = MagicMock()
    response.json = lambda: [{"generated_text": "answer"}]
    http.post = AsyncMock(return_value=response)

    tgi = TgiBatchClient(base_url="http://tgi:80", http_client=http, concurrency=5)
    results = await tgi.batch_completions(
        ["q1", "q2", "q3"], model="model-a", max_tokens=50
    )
    assert results == ["answer", "answer", "answer"]
    assert http.post.await_count == 3


@pytest.mark.asyncio
async def test_tgi_batch_completions_empty_input() -> None:
    http = AsyncMock()
    tgi = TgiBatchClient(base_url="http://tgi:80", http_client=http)
    result = await tgi.batch_completions([], model="m")
    assert result == []
    http.post.assert_not_awaited()


@pytest.mark.asyncio
async def test_tgi_batch_embeddings() -> None:
    http = AsyncMock()
    response = MagicMock()
    response.json = lambda: [[0.1, 0.2, 0.3]]
    http.post = AsyncMock(return_value=response)

    tgi = TgiBatchClient(base_url="http://tgi:80", http_client=http)
    result = await tgi.batch_embeddings(["text1", "text2"], model="embed-model")
    assert len(result) == 2
    assert result[0] == [0.1, 0.2, 0.3]


@pytest.mark.asyncio
async def test_tgi_handles_dict_response() -> None:
    http = AsyncMock()
    response = MagicMock()
    response.json = lambda: {"generated_text": "dict-response"}
    http.post = AsyncMock(return_value=response)

    tgi = TgiBatchClient(base_url="http://tgi:80", http_client=http)
    results = await tgi.batch_completions(["q"], model="m")
    assert results == ["dict-response"]


@pytest.mark.asyncio
async def test_vllm_completions_uses_provided_engine() -> None:
    """vLLM client использует переданный engine без import vllm."""

    class _FakeOutput:
        def __init__(self) -> None:
            self.finished = True

            class _O:
                text = "vllm-gen"

            self.outputs = [_O()]

    async def _generate_stream(prompt: str, sampling: Any, request_id: str):
        yield _FakeOutput()

    engine = MagicMock()
    engine.generate = _generate_stream

    vllm = VllmBatchClient(engine=engine)
    # batch_completions требует vllm.SamplingParams — мокаем sys.modules.
    import sys
    import types

    fake_vllm = types.ModuleType("vllm")

    class _SP:
        def __init__(self, temperature=0.0, max_tokens=256) -> None:
            self.temperature = temperature
            self.max_tokens = max_tokens

    fake_vllm.SamplingParams = _SP
    sys.modules["vllm"] = fake_vllm
    try:
        results = await vllm.batch_completions(["q1", "q2"], model="m", max_tokens=10)
        assert results == ["vllm-gen", "vllm-gen"]
    finally:
        sys.modules.pop("vllm", None)


@pytest.mark.asyncio
async def test_vllm_embeddings_raises() -> None:
    vllm = VllmBatchClient(engine=MagicMock())
    with pytest.raises(NotImplementedError):
        await vllm.batch_embeddings(["x"], model="m")
