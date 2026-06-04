"""Tests for src.backend.core.config.waf."""

from __future__ import annotations

import pytest

from src.backend.core.config.waf import WafSettings


class TestWafSettings:
    def test_defaults(self) -> None:
        s = WafSettings()
        assert s.strict is False
        assert s.max_payload_bytes == 10 * 1024 * 1024
        assert s.clamav_enabled is False
        assert s.clamav_fail_open is True

    def test_custom(self) -> None:
        s = WafSettings(
            strict=True,
            max_payload_bytes=1024,
            clamav_host="clamav",
            clamav_fail_open=False,
        )
        assert s.strict is True
        assert s.max_payload_bytes == 1024
        assert s.clamav_host == "clamav"
        assert s.clamav_fail_open is False

    def test_bounds(self) -> None:
        with pytest.raises(Exception):
            WafSettings(max_payload_bytes=-1)
        with pytest.raises(Exception):
            WafSettings(clamav_port=0)
