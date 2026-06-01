"""Тесты ClamAVPayloadScanner (Sprint 16 Wave 6, B-3 finale)."""

# ruff: noqa: S101

from __future__ import annotations

import pytest

from src.backend.core.interfaces.antivirus import AntivirusBackend, AntivirusScanResult
from src.backend.infrastructure.antivirus.payload_scanner import ClamAVPayloadScanner


class _CleanBackend(AntivirusBackend):
    name = "fake_clean"

    async def is_available(self) -> bool:
        return True

    async def scan_bytes(self, payload: bytes) -> AntivirusScanResult:
        return AntivirusScanResult(
            clean=True, signature=None, backend=self.name, latency_ms=1.0
        )


class _InfectedBackend(AntivirusBackend):
    name = "fake_infected"

    async def is_available(self) -> bool:
        return True

    async def scan_bytes(self, payload: bytes) -> AntivirusScanResult:
        return AntivirusScanResult(
            clean=False,
            signature="Eicar-Test-Signature",
            backend=self.name,
            latency_ms=1.0,
        )


class _UnavailableBackend(AntivirusBackend):
    name = "fake_unavailable"

    async def is_available(self) -> bool:
        return False

    async def scan_bytes(self, payload: bytes) -> AntivirusScanResult:
        raise ConnectionError("clamd недоступен")


class _CrashingBackend(AntivirusBackend):
    name = "fake_crashing"

    async def is_available(self) -> bool:
        return True

    async def scan_bytes(self, payload: bytes) -> AntivirusScanResult:
        raise RuntimeError("unexpected parser error")


@pytest.mark.asyncio
async def test_clean_payload_returns_none() -> None:
    scanner = ClamAVPayloadScanner(_CleanBackend())
    assert await scanner(b"hello") is None


@pytest.mark.asyncio
async def test_infected_payload_returns_signature() -> None:
    scanner = ClamAVPayloadScanner(_InfectedBackend())
    reason = await scanner(b"X5O!P%@AP[4\\PZX54(P^)7CC)7}$EICAR")
    assert reason is not None
    assert "Eicar" in reason


@pytest.mark.asyncio
async def test_none_payload_skipped() -> None:
    scanner = ClamAVPayloadScanner(_InfectedBackend())
    assert await scanner(None) is None


@pytest.mark.asyncio
async def test_empty_payload_skipped() -> None:
    scanner = ClamAVPayloadScanner(_InfectedBackend())
    assert await scanner(b"") is None


@pytest.mark.asyncio
async def test_unavailable_backend_fail_open_returns_none() -> None:
    scanner = ClamAVPayloadScanner(_UnavailableBackend(), fail_open=True)
    assert await scanner(b"any") is None


@pytest.mark.asyncio
async def test_unavailable_backend_fail_closed_blocks() -> None:
    scanner = ClamAVPayloadScanner(_UnavailableBackend(), fail_open=False)
    reason = await scanner(b"any")
    assert reason == "clamav unavailable"


@pytest.mark.asyncio
async def test_unexpected_error_fail_open_returns_none() -> None:
    scanner = ClamAVPayloadScanner(_CrashingBackend(), fail_open=True)
    assert await scanner(b"any") is None


@pytest.mark.asyncio
async def test_unexpected_error_fail_closed_blocks_with_type() -> None:
    scanner = ClamAVPayloadScanner(_CrashingBackend(), fail_open=False)
    reason = await scanner(b"any")
    assert reason == "clamav error: RuntimeError"
