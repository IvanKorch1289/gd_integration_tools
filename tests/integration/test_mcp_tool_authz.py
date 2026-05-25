"""Integration test для Block 1.4 (gap-ai-1.4, ADR-0072/0070).

Проверяет per-tool authz для MCP dispatch:

1. ``mcp_settings.tool_authz_enabled=False`` (default) → passthrough,
   все actions доступны.
2. ``tool_authz_enabled=True`` без allowlist + не-public namespace →
   deny с reason ``not_in_allowlist_or_public_ns``.
3. ``tool_authz_enabled=True`` + action в ``tool_allowlist`` → allow.
4. ``tool_authz_enabled=True`` + action в public namespace (``system.*``) → allow.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.integration


def test_authz_passthrough_when_disabled(monkeypatch: pytest.MonkeyPatch) -> None:
    """При tool_authz_enabled=False все actions допускаются."""
    from src.backend.core.config import ai_2026
    from src.backend.entrypoints.mcp.mcp_server import _check_mcp_tool_authz

    monkeypatch.setattr(
        ai_2026.mcp_settings, "tool_authz_enabled", False, raising=True
    )
    assert _check_mcp_tool_authz("custom.action") is None
    assert _check_mcp_tool_authz("admin.purge") is None


def test_authz_deny_when_enabled_and_not_in_allowlist(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """При tool_authz_enabled=True без allowlist + не-public namespace → deny."""
    from src.backend.core.config import ai_2026
    from src.backend.entrypoints.mcp.mcp_server import _check_mcp_tool_authz

    monkeypatch.setattr(
        ai_2026.mcp_settings, "tool_authz_enabled", True, raising=True
    )
    monkeypatch.setattr(ai_2026.mcp_settings, "tool_allowlist", [], raising=True)
    monkeypatch.setattr(
        ai_2026.mcp_settings,
        "tool_public_namespaces",
        ["system", "health"],
        raising=True,
    )

    reason = _check_mcp_tool_authz("credit.score.calculate")
    assert reason == "not_in_allowlist_or_public_ns"

    reason = _check_mcp_tool_authz("admin.dlq.replay")
    assert reason == "not_in_allowlist_or_public_ns"


def test_authz_allow_when_in_explicit_allowlist(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """action_name в tool_allowlist → allow."""
    from src.backend.core.config import ai_2026
    from src.backend.entrypoints.mcp.mcp_server import _check_mcp_tool_authz

    monkeypatch.setattr(
        ai_2026.mcp_settings, "tool_authz_enabled", True, raising=True
    )
    monkeypatch.setattr(
        ai_2026.mcp_settings,
        "tool_allowlist",
        ["credit.score.calculate", "rag.retrieve"],
        raising=True,
    )
    monkeypatch.setattr(
        ai_2026.mcp_settings, "tool_public_namespaces", [], raising=True
    )

    assert _check_mcp_tool_authz("credit.score.calculate") is None
    assert _check_mcp_tool_authz("rag.retrieve") is None
    assert _check_mcp_tool_authz("other.action") == "not_in_allowlist_or_public_ns"


def test_authz_allow_when_namespace_is_public(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """action в public namespace → allow."""
    from src.backend.core.config import ai_2026
    from src.backend.entrypoints.mcp.mcp_server import _check_mcp_tool_authz

    monkeypatch.setattr(
        ai_2026.mcp_settings, "tool_authz_enabled", True, raising=True
    )
    monkeypatch.setattr(ai_2026.mcp_settings, "tool_allowlist", [], raising=True)
    monkeypatch.setattr(
        ai_2026.mcp_settings,
        "tool_public_namespaces",
        ["system", "health", "tech"],
        raising=True,
    )

    assert _check_mcp_tool_authz("system.status") is None
    assert _check_mcp_tool_authz("health.live") is None
    assert _check_mcp_tool_authz("tech.metrics") is None
    assert _check_mcp_tool_authz("credit.score") == "not_in_allowlist_or_public_ns"


def test_authz_handles_action_without_namespace(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """action без точки в имени (legacy) корректно обрабатывается."""
    from src.backend.core.config import ai_2026
    from src.backend.entrypoints.mcp.mcp_server import _check_mcp_tool_authz

    monkeypatch.setattr(
        ai_2026.mcp_settings, "tool_authz_enabled", True, raising=True
    )
    monkeypatch.setattr(
        ai_2026.mcp_settings, "tool_allowlist", ["legacy_action"], raising=True
    )
    monkeypatch.setattr(
        ai_2026.mcp_settings, "tool_public_namespaces", [], raising=True
    )

    assert _check_mcp_tool_authz("legacy_action") is None
    assert _check_mcp_tool_authz("other_action") == "not_in_allowlist_or_public_ns"
