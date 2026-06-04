"""Тесты async-pathway WafPolicy (Sprint 16 Wave 6, B-3 finale)."""

# ruff: noqa: S101

from __future__ import annotations

from typing import Any

import pytest

from src.backend.core.net.waf import WafPolicy


@pytest.mark.asyncio
async def test_evaluate_async_clean_payload_returns_allowed() -> None:
    """Чистый payload без scanner'а → allowed=True."""
    policy = WafPolicy(allow_hosts=frozenset({"api.example.com"}), strict=True)
    decision = await policy.evaluate_async(
        "https://api.example.com/v1/x", payload=b"hello"
    )
    assert decision.allowed is True
    assert decision.host == "api.example.com"


@pytest.mark.asyncio
async def test_evaluate_async_invokes_async_scanner_and_blocks() -> None:
    """async_payload_scanner возвращает причину → WafDecision.allowed=False."""

    async def virus_scanner(payload: bytes | None) -> str | None:
        return "ClamAV signature: Eicar-Test-Signature"

    policy = WafPolicy(async_payload_scanner=virus_scanner)
    decision = await policy.evaluate_async(
        "https://api.example.com/x", payload=b"X5O!P%@AP[4\\PZX54(P^)7CC)7}$EICAR"
    )
    assert decision.allowed is False
    assert "Eicar" in decision.reason


@pytest.mark.asyncio
async def test_evaluate_async_clean_scanner_passes() -> None:
    """async_payload_scanner вернул None → allowed=True."""

    async def clean_scanner(_payload: bytes | None) -> str | None:
        return None

    policy = WafPolicy(async_payload_scanner=clean_scanner)
    decision = await policy.evaluate_async("https://api.example.com/x", payload=b"safe")
    assert decision.allowed is True


@pytest.mark.asyncio
async def test_evaluate_async_skip_scanner_when_payload_none() -> None:
    """payload=None → async scanner не вызывается."""
    calls: list[bytes | None] = []

    async def tracking_scanner(payload: bytes | None) -> str | None:
        calls.append(payload)
        return None

    policy = WafPolicy(async_payload_scanner=tracking_scanner)
    decision = await policy.evaluate_async("https://api.example.com/x", payload=None)
    assert decision.allowed is True
    assert calls == []


@pytest.mark.asyncio
async def test_evaluate_async_deny_list_short_circuits_scanner() -> None:
    """Хост в deny_hosts → scanner не вызывается, allowed=False."""
    calls: list[bytes | None] = []

    async def should_not_run(payload: bytes | None) -> str | None:
        calls.append(payload)
        return None

    policy = WafPolicy(
        deny_hosts=frozenset({"evil.example.com"}), async_payload_scanner=should_not_run
    )
    decision = await policy.evaluate_async("https://evil.example.com/x", payload=b"any")
    assert decision.allowed is False
    assert "deny_hosts" in decision.reason
    assert calls == []


@pytest.mark.asyncio
async def test_evaluate_async_strict_blocks_unknown_host() -> None:
    """strict=True + хост вне allow_hosts → блокировка ДО scanner'а."""
    calls: list[bytes | None] = []

    async def should_not_run(payload: bytes | None) -> str | None:
        calls.append(payload)
        return None

    policy = WafPolicy(
        allow_hosts=frozenset({"api.example.com"}),
        strict=True,
        async_payload_scanner=should_not_run,
    )
    decision = await policy.evaluate_async(
        "https://random.example.com/x", payload=b"any"
    )
    assert decision.allowed is False
    assert "allow_hosts" in decision.reason
    assert calls == []


@pytest.mark.asyncio
async def test_evaluate_async_payload_limit_blocks_before_scanner() -> None:
    """payload > max_payload_bytes → block ДО async scanner'а."""
    called = False

    async def should_not_run(_payload: bytes | None) -> str | None:
        nonlocal called
        called = True
        return None

    policy = WafPolicy(max_payload_bytes=10, async_payload_scanner=should_not_run)
    decision = await policy.evaluate_async(
        "https://api.example.com/x", payload=b"more than ten bytes here"
    )
    assert decision.allowed is False
    assert "exceeds limit" in decision.reason
    assert called is False


@pytest.mark.asyncio
async def test_evaluate_async_sync_scanner_runs_before_async() -> None:
    """sync payload_scanner вызывается раньше async_payload_scanner."""
    invoked: list[str] = []

    def sync_scanner(_payload: bytes | None) -> str | None:
        invoked.append("sync")
        return None

    async def async_scanner(_payload: bytes | None) -> str | None:
        invoked.append("async")
        return None

    policy = WafPolicy(
        payload_scanner=sync_scanner, async_payload_scanner=async_scanner
    )
    await policy.evaluate_async("https://api.example.com/x", payload=b"x")
    assert invoked == ["sync", "async"]


def test_evaluate_sync_ignores_async_scanner() -> None:
    """Sync evaluate() НЕ вызывает async_payload_scanner."""
    invoked = False

    async def should_not_run(_p: Any) -> str | None:
        nonlocal invoked
        invoked = True
        return "boom"

    policy = WafPolicy(async_payload_scanner=should_not_run)
    decision = policy.evaluate("https://api.example.com/x", payload=b"any")
    assert decision.allowed is True
    assert invoked is False
