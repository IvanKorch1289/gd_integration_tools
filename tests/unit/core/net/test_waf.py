"""Тесты :class:`WafPolicy` (V15 R-V15-5).

Покрывают пять веток ``evaluate``:

* невалидный URL → denied;
* deny_hosts приоритет;
* strict-режим + allow_hosts mismatch;
* payload-limit;
* payload-scanner.
"""

from __future__ import annotations

import pytest

from src.backend.core.net.waf import (
    WafPolicy,
    build_default_policy,
)


def test_evaluate_allows_unknown_host_in_permissive_mode() -> None:
    """В non-strict пустой allow_hosts разрешает всё."""
    policy = WafPolicy()
    decision = policy.evaluate("https://example.com/path")
    assert decision.allowed is True
    assert decision.host == "example.com"


def test_evaluate_blocks_invalid_url() -> None:
    """URL без host блокируется (fail-closed)."""
    policy = WafPolicy()
    decision = policy.evaluate("not-a-url")
    assert decision.allowed is False
    assert decision.host == ""


def test_evaluate_blocks_deny_listed_host() -> None:
    """deny_hosts имеет приоритет над allow_hosts."""
    policy = WafPolicy(
        allow_hosts=frozenset({"banned.example.com"}),
        deny_hosts=frozenset({"banned.example.com"}),
    )
    decision = policy.evaluate("https://banned.example.com/x")
    assert decision.allowed is False
    assert "deny_hosts" in decision.reason


def test_evaluate_strict_mode_blocks_unknown_host() -> None:
    """strict + non-empty allow_hosts → fail-closed для чужого хоста."""
    policy = WafPolicy(
        allow_hosts=frozenset({"trusted.example.com"}),
        strict=True,
    )
    decision = policy.evaluate("https://other.example.com/path")
    assert decision.allowed is False
    assert "allow_hosts" in decision.reason


def test_evaluate_strict_mode_allows_listed_host() -> None:
    """strict + host в allow_hosts → granted."""
    policy = WafPolicy(
        allow_hosts=frozenset({"trusted.example.com"}),
        strict=True,
    )
    decision = policy.evaluate("https://trusted.example.com/x")
    assert decision.allowed is True


def test_evaluate_blocks_oversized_payload() -> None:
    """payload > max_payload_bytes → blocked."""
    policy = WafPolicy(max_payload_bytes=10)
    decision = policy.evaluate("https://example.com/", payload=b"X" * 100)
    assert decision.allowed is False
    assert "exceeds limit" in decision.reason


def test_evaluate_runs_payload_scanner() -> None:
    """Scanner-возврат не-None → blocked."""

    def scanner(payload: bytes | None) -> str | None:
        if payload and b"<script>" in payload:
            return "xss-attempt"
        return None

    policy = WafPolicy(payload_scanner=scanner)
    decision = policy.evaluate(
        "https://example.com/", payload=b"<script>alert(1)</script>"
    )
    assert decision.allowed is False
    assert decision.reason == "xss-attempt"


def test_default_policy_has_payload_limit() -> None:
    """build_default_policy возвращает разумный default."""
    policy = build_default_policy()
    assert policy.max_payload_bytes is not None
    assert policy.strict is False


@pytest.mark.parametrize(
    "url",
    [
        "http://example.com",
        "https://example.com:8443/path?q=1",
        "ftp://example.com/file",
    ],
)
def test_evaluate_extracts_host_from_various_schemes(url: str) -> None:
    """Хост извлекается из любой URL-схемы с явным host."""
    decision = WafPolicy().evaluate(url)
    assert decision.host == "example.com"
