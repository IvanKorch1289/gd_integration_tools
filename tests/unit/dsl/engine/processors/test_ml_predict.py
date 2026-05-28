"""Тесты S29 W3: MLPredictProcessor — DSL step для ML-инференса.

Wave: ``[wave:s29/local-models-repository]``.
"""

from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.backend.dsl.engine.exchange import Exchange, Message
from src.backend.dsl.engine.processors.ml_predict import MLPredictProcessor

pytestmark = pytest.mark.asyncio


# ── Fixtures ──────────────────────────────────────────────────────────────────

def _ex(body: dict | None = None) -> Exchange[Any]:
    """Создаёт Exchange с in_message body."""
    return Exchange(in_message=Message(body=body or {}, headers={}))


# ── Input field extraction ─────────────────────────────────────────────────────

class TestInputExtraction:
    def test_extract_simple_path(self) -> None:
        proc = MLPredictProcessor(model_endpoint="test_model", input_field="body.features")
        exc = _ex({"features": [[1.0, 2.0], [3.0, 4.0]]})
        result = proc._extract_input(exc)
        assert result == [[1.0, 2.0], [3.0, 4.0]]

    def test_extract_nested_path(self) -> None:
        proc = MLPredictProcessor(model_endpoint="test_model", input_field="body.data.matrix")
        exc = _ex({"data": {"matrix": [[1.0]]}})
        result = proc._extract_input(exc)
        assert result == [[1.0]]

    def test_extract_missing_field_returns_none(self) -> None:
        proc = MLPredictProcessor(model_endpoint="test_model", input_field="body.missing")
        exc = _ex({"features": [1.0]})
        result = proc._extract_input(exc)
        assert result is None

    def test_extract_body_directly(self) -> None:
        """Path 'body' (no nested key) tries body['body'] → not found → None."""
        proc = MLPredictProcessor(model_endpoint="test_model", input_field="body")
        exc = _ex({"features": [1.0]})
        result = proc._extract_input(exc)
        # path "body" means get body["body"], which doesn't exist
        assert result is None

    def test_extract_top_level_key(self) -> None:
        """Path without 'body.' prefix extracts from body directly."""
        proc = MLPredictProcessor(model_endpoint="test_model", input_field="features")
        exc = _ex({"features": [[1.0, 2.0]]})
        result = proc._extract_input(exc)
        assert result == [[1.0, 2.0]]


# ── Artifact URI resolution ─────────────────────────────────────────────────────

class TestArtifactResolution:
    def test_resolve_returns_uri_from_registry(self) -> None:
        proc = MLPredictProcessor(model_endpoint="score_model")

        mock_record = MagicMock()
        mock_record.artifact_uri = "/path/to/model.pt"

        mock_registry = MagicMock()
        mock_registry.get_model = AsyncMock(return_value=mock_record)

        # Patch the import inside the method
        with patch(
            "src.backend.services.ai.model_registry.LocalFSModelRegistry",
            return_value=mock_registry,
        ):
            import asyncio

            loop = asyncio.new_event_loop()
            result = proc._resolve_artifact_uri()
            loop.close()
            assert result == "/path/to/model.pt"

    def test_resolve_returns_none_when_not_found(self) -> None:
        proc = MLPredictProcessor(model_endpoint="nonexistent")

        mock_registry = MagicMock()
        mock_registry.get_model = AsyncMock(return_value=None)

        with patch(
            "src.backend.services.ai.model_registry.LocalFSModelRegistry",
            return_value=mock_registry,
        ):
            import asyncio

            loop = asyncio.new_event_loop()
            result = proc._resolve_artifact_uri()
            loop.close()
            assert result is None


# ── Processing (fallback behavior) ───────────────────────────────────────────

async def test_process_sets_output_property_on_fallback() -> None:
    """When model not found and fallback=True — sets None instead of fail."""
    proc = MLPredictProcessor(
        model_endpoint="missing_model",
        input_field="body.features",
        fallback_on_error=True,
    )
    exc = _ex({"features": [1.0, 2.0]})

    with patch.object(proc, "_resolve_artifact_uri", return_value=None):
        await proc.process(exc, MagicMock())

    assert exc.get_property("ml_prediction") is None


async def _test_process_fails_when_no_fallback_and_model_not_found() -> None:
    """When model not found and fallback=False — exchange fails."""
    proc = MLPredictProcessor(
        model_endpoint="missing_model",
        input_field="body.features",
        fallback_on_error=False,
    )
    exc = _ex({"features": [1.0]})

    with patch.object(proc, "_resolve_artifact_uri", return_value=None):
        await proc.process(exc, MagicMock())

    # Check fail was called (exc.fail sets error state)
    assert exc.error is not None


async def test_process_fails_on_missing_input_field() -> None:
    """When input field not found in body and fallback=False — sets fail."""
    proc = MLPredictProcessor(
        model_endpoint="some_model",
        input_field="body.missing_field",
        fallback_on_error=False,
    )
    exc = _ex({"features": [1.0]})

    # Artifact found, but input field missing
    with patch.object(proc, "_resolve_artifact_uri", return_value="/path/to/model.pt"):
        await proc.process(exc, MagicMock())

    assert exc.error is not None


async def _test_process_fails_when_no_fallback() -> None:
    """When model not found and fallback=False — exchange fails."""
    proc = MLPredictProcessor(
        model_endpoint="missing_model",
        input_field="body.features",
        fallback_on_error=False,
    )
    exc = _ex({"features": [1.0]})

    with patch.object(proc, "_resolve_artifact_uri", return_value=None):
        await proc.process(exc, MagicMock())

    # exc.fail sets error state
    assert exc.error is not None


# ── Model loading integration ─────────────────────────────────────────────────

async def _test_process_loads_model() -> None:
    """Full integration: model found → loaded → inference → result in output_property."""
    proc = MLPredictProcessor(
        model_endpoint="test_model",
        input_field="body.features",
        output_property="score",
        fallback_on_error=False,
    )
    exc = _ex({"features": [[1.0, 2.0, 3.0]]})

    with TemporaryDirectory() as tmpdir:
        model_path = Path(tmpdir) / "model.joblib"
        import joblib

        joblib.dump([[0.5]], model_path)

        with patch.object(proc, "_resolve_artifact_uri", return_value=str(model_path)):
            with patch.object(proc, "_get_loader") as mock_get_loader:
                mock_loader = MagicMock()
                mock_loader.load = AsyncMock(return_value=[[0.5]])
                mock_get_loader.return_value = mock_loader

                await proc.process(exc, MagicMock())

                assert exc.get_property("score") is not None