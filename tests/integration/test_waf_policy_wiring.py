# ruff: noqa: S101
"""Интеграционные тесты Wave 1.4: register_waf_policy + register_outbound_http_client."""

from __future__ import annotations

from typing import Any

import pytest

from src.backend.core.net.outbound_http import OutboundHttpClient
from src.backend.core.net.waf import WafBypassError, WafPolicy
from src.backend.core.svcs_registry import (
    clear_registry,
    get_service,
    has_service,
    register_factory,
)


@pytest.fixture(autouse=True)
def _clean_registry():
    """Перед каждым тестом — чистый svcs-registry."""
    clear_registry()
    yield
    clear_registry()


def test_register_waf_policy_creates_singleton() -> None:
    from src.backend.plugins.composition.waf_setup import register_waf_policy

    register_waf_policy()
    assert has_service(WafPolicy)
    p1 = get_service(WafPolicy)
    p2 = get_service(WafPolicy)
    assert p1 is p2


def test_register_waf_policy_idempotent() -> None:
    from src.backend.plugins.composition.waf_setup import register_waf_policy

    register_waf_policy()
    register_waf_policy()
    assert has_service(WafPolicy)


def test_register_outbound_http_client_provides_singleton() -> None:
    from src.backend.plugins.composition.waf_setup import (
        register_outbound_http_client,
        register_waf_policy,
    )

    register_waf_policy()
    register_outbound_http_client()
    client = get_service(OutboundHttpClient)
    assert isinstance(client, OutboundHttpClient)


def test_outbound_http_client_strict_denied_host(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """strict=True + denied host → WafBypassError при request()."""
    custom = WafPolicy(allow_hosts=frozenset({"trusted.example.com"}), strict=True)
    register_factory(WafPolicy, lambda: custom)
    from src.backend.plugins.composition.waf_setup import register_outbound_http_client

    register_outbound_http_client()
    client = get_service(OutboundHttpClient)
    decision = client._policy.evaluate("https://evil.example.com/x")
    assert decision.allowed is False
    assert decision.reason == "host not in allow_hosts (strict)"


def test_audit_callback_receives_event(caplog: pytest.LogCaptureFixture) -> None:
    """waf_audit_callback пишет outcome в logger ``waf.audit``."""
    from src.backend.plugins.composition.waf_setup import waf_audit_callback

    caplog.set_level("INFO", logger="waf.audit")
    waf_audit_callback(
        {
            "plugin": "core",
            "method": "GET",
            "host": "example.com",
            "url": "https://example.com/",
            "allowed": True,
            "reason": "allowed",
        }
    )
    record = next(r for r in caplog.records if r.name == "waf.audit")
    assert getattr(record, "waf_outcome") == "granted"
    assert getattr(record, "host") == "example.com"


def test_capability_denied_when_gate_present_without_declaration() -> None:
    """OutboundHttpClient + CapabilityGate без декларации → CapabilityDeniedError."""
    from src.backend.core.security.capabilities.errors import CapabilityDeniedError
    from src.backend.core.security.capabilities.gate import CapabilityGate
    from src.backend.plugins.composition.waf_setup import (
        register_outbound_http_client,
        register_waf_policy,
    )

    register_factory(CapabilityGate, lambda: CapabilityGate())
    register_waf_policy()
    register_outbound_http_client()
    client = get_service(OutboundHttpClient)

    # Прямой вызов capability_check без url-вызова — net.outbound не задекларирован.
    assert client._capability_check is not None
    with pytest.raises(CapabilityDeniedError):
        client._capability_check("core", "net.outbound", "example.com")


@pytest.mark.asyncio
async def test_outbound_http_client_raises_on_strict_violation() -> None:
    """End-to-end: strict + не allowed host → WafBypassError при request()."""
    custom = WafPolicy(allow_hosts=frozenset({"trusted.example.com"}), strict=True)
    register_factory(WafPolicy, lambda: custom)
    from src.backend.plugins.composition.waf_setup import register_outbound_http_client

    register_outbound_http_client()
    client = get_service(OutboundHttpClient)
    with pytest.raises(WafBypassError):
        await client.request("GET", "https://evil.example.com/x")
    await client.aclose()


def test_outbound_http_client_idempotent() -> None:
    from src.backend.plugins.composition.waf_setup import (
        register_outbound_http_client,
        register_waf_policy,
    )

    register_waf_policy()
    register_outbound_http_client()
    register_outbound_http_client()
    assert has_service(OutboundHttpClient)
