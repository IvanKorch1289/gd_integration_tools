"""Unit tests for src.backend.core.interfaces.antivirus."""

from __future__ import annotations

import pytest

from src.backend.core.interfaces.antivirus import AntivirusBackend, AntivirusScanResult


class TestAntivirusScanResult:
    def test_defaults(self) -> None:
        res = AntivirusScanResult(clean=True)
        assert res.clean is True
        assert res.signature is None
        assert res.backend == ""
        assert res.latency_ms is None

    def test_full(self) -> None:
        res = AntivirusScanResult(
            clean=False, signature="EICAR", backend="clamav", latency_ms=12.5
        )
        assert res.clean is False
        assert res.signature == "EICAR"
        assert res.backend == "clamav"
        assert res.latency_ms == 12.5


class TestAntivirusBackend:
    def test_cannot_instantiate(self) -> None:
        with pytest.raises(TypeError):
            AntivirusBackend()  # type: ignore[abstract]

    def test_subclass_must_implement(self) -> None:
        class Partial(AntivirusBackend):
            async def scan_bytes(self, payload: bytes) -> AntivirusScanResult:
                return AntivirusScanResult(clean=True)

        with pytest.raises(TypeError):
            Partial()  # type: ignore[abstract]

    def test_valid_subclass(self) -> None:
        class Full(AntivirusBackend):
            async def scan_bytes(self, payload: bytes) -> AntivirusScanResult:
                return AntivirusScanResult(clean=True)

            async def is_available(self) -> bool:
                return True

        inst = Full()
        assert inst.name == "base"
