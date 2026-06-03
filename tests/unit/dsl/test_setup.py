"""Tests for dsl/setup.py."""

from __future__ import annotations

from unittest.mock import patch

from src.backend.dsl.setup import bootstrap_dsl


class TestBootstrapDsl:
    def test_calls_in_order(self) -> None:
        with (
            patch("src.backend.dsl.setup.register_action_handlers") as rah,
            patch("src.backend.dsl.setup.register_dsl_routes") as rdr,
            patch("src.backend.dsl.setup._register_adapters") as ra,
        ):
            bootstrap_dsl()
        rah.assert_called_once()
        rdr.assert_called_once()
        ra.assert_called_once()
