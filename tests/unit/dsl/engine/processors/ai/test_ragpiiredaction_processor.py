"""Unit tests for RagPIIRedactionProcessor."""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from src.backend.dsl.engine.processors.ai.ragpiiredaction_processor import (
    RagPIIRedactionProcessor,
)


class _Message:
    def __init__(self, body: Any = None) -> None:
        self.body = body


class _Exchange:
    def __init__(self, properties: dict[str, Any] | None = None) -> None:
        self.in_message = _Message()
        self.properties: dict[str, Any] = properties or {}

    def set_property(self, key: str, value: Any) -> None:
        self.properties[key] = value


class _Context:
    pass


class TestRagPIIRedactionProcessor:
    """Tests for :class:`RagPIIRedactionProcessor`."""

    @pytest.mark.asyncio
    async def test_feature_off_is_noop(self) -> None:
        exchange = _Exchange()
        exchange.set_property("augment_result", {"prompt": "secret"})
        proc = RagPIIRedactionProcessor()

        with patch("src.backend.core.config.features.feature_flags") as mock_flags:
            mock_flags.rag_pii_retrieval_mask = False
            await proc.process(exchange, _Context())

        assert exchange.properties["augment_result"] == {"prompt": "secret"}

    @pytest.mark.asyncio
    async def test_feature_on_masks_dict(self) -> None:
        exchange = _Exchange()
        exchange.set_property("augment_result", {"prompt": "secret"})
        proc = RagPIIRedactionProcessor()

        with (
            patch("src.backend.core.config.features.feature_flags") as mock_flags,
            patch(
                "src.backend.services.ai.pii.retrieval_masker.mask_augment_result",
                return_value={"prompt": "masked"},
            ) as mock_mask,
        ):
            mock_flags.rag_pii_retrieval_mask = True
            await proc.process(exchange, _Context())

        mock_mask.assert_called_once_with({"prompt": "secret"})
        assert exchange.properties["augment_result"] == {"prompt": "masked"}

    @pytest.mark.asyncio
    async def test_non_dict_payload_is_noop(self) -> None:
        exchange = _Exchange()
        exchange.set_property("augment_result", "not a dict")
        proc = RagPIIRedactionProcessor()

        with (
            patch("src.backend.core.config.features.feature_flags") as mock_flags,
            patch(
                "src.backend.services.ai.pii.retrieval_masker.mask_augment_result"
            ) as mock_mask,
        ):
            mock_flags.rag_pii_retrieval_mask = True
            await proc.process(exchange, _Context())

        mock_mask.assert_not_called()
        assert exchange.properties["augment_result"] == "not a dict"

    @pytest.mark.asyncio
    async def test_custom_input_output_properties(self) -> None:
        exchange = _Exchange()
        exchange.set_property("in_prop", {"data": 1})
        proc = RagPIIRedactionProcessor(
            input_property="in_prop", output_property="out_prop"
        )

        with (
            patch("src.backend.core.config.features.feature_flags") as mock_flags,
            patch(
                "src.backend.services.ai.pii.retrieval_masker.mask_augment_result",
                return_value={"data": 2},
            ) as mock_mask,
        ):
            mock_flags.rag_pii_retrieval_mask = True
            await proc.process(exchange, _Context())

        mock_mask.assert_called_once_with({"data": 1})
        assert exchange.properties["out_prop"] == {"data": 2}

    def test_to_spec_defaults(self) -> None:
        proc = RagPIIRedactionProcessor()
        assert proc.to_spec() == {"rag_pii_redact": {}}

    def test_to_spec_custom(self) -> None:
        proc = RagPIIRedactionProcessor(input_property="in", output_property="out")
        assert proc.to_spec() == {
            "rag_pii_redact": {"input_property": "in", "output_property": "out"}
        }
