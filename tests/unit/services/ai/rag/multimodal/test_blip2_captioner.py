"""Тесты Sprint 11 K4 W1 — BLIP2 captioner (mock-проводник)."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from src.backend.services.ai.rag.multimodal.blip2_captioner import (
    BLIP2Captioner,
    CaptionResult,
)


def test_blip2_no_transformers_raises_on_load(monkeypatch: pytest.MonkeyPatch) -> None:
    """Без transformers _load() бросает RuntimeError с подсказкой extra."""
    captioner = BLIP2Captioner(model_name="x")

    import builtins

    real_import = builtins.__import__

    def _fail(name: str, *args, **kwargs):  # type: ignore[no-untyped-def]
        if name == "transformers" or name.startswith("transformers."):
            raise ImportError("No module named 'transformers'")
        return real_import(name, *args, **kwargs)

    monkeypatch.setattr(builtins, "__import__", _fail)
    with pytest.raises(RuntimeError) as exc:
        captioner._load()
    assert "multimodal-rag" in str(exc.value)


def test_blip2_captioner_construction() -> None:
    """Конструктор не тянет ML-deps — _model инициализируется только в _load()."""
    captioner = BLIP2Captioner(model_name="custom", device="cpu")
    assert captioner._model is None
    assert captioner._processor is None
    assert captioner._model_name == "custom"
    assert captioner._device == "cpu"


def test_caption_result_dataclass_is_frozen() -> None:
    """CaptionResult иммутабелен — нельзя случайно перезаписать caption."""
    result = CaptionResult(caption="a", model="m", device="cpu")
    with pytest.raises(Exception):
        result.caption = "b"  # type: ignore[misc]
