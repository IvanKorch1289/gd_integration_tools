"""S79 W1 — AIPolicySpec.tools integration с CapabilityGate (P0-B follow-up).

FINAL_REPORT_V2 направление #4: "CapabilityGate не ограничивает
конкретные инструменты". До S79: :class:`AIPolicySpec.tools`
(S76 W1) — whitelist/blacklist существует, но :class:`CapabilityGate`
его НЕ consult'ил. S79 W1: integration layer, который checks
tool call against BOTH layers (capability declaration + AIPolicySpec).

**Two-layer enforcement**:
1. **CapabilityGate.check(plugin, capability, scope)** — existing
   (S36/S54). Validates plugin declared capability, scope coverage,
   policy consultation. Failure → :exc:`CapabilityDeniedError`.
2. **AIPolicySpec.tools whitelist/blacklist** (S76). Validates
   tool name against per-policy allowlist/denylist. Failure →
   :exc:`ToolPolicyViolationError` (S76 W2).

**Two-layer invocation order** (S79 W1 design):
1. Caller calls :func:`check_tool_with_policy` (NEW, S79 W1).
2. First checks :class:`CapabilityGate.check` (capability declared?).
3. Then checks :func:`enforce_tool_policy` (AIPolicySpec.tools).
4. Both must pass for invocation to proceed.

Use case: agent хочет invoke ``db.read.orders``:
1. CapabilityGate: plugin X declared ``db.read.orders``? Yes.
2. AIPolicySpec.tools: ``db.read.orders`` in whitelist? If whitelist
   is ``["db.read.orders", "ai.invoke.credit_check"]`` — yes, OK.
   If whitelist is ``["ai.invoke.credit_check"]`` — fail
   (ToolPolicyViolationError).

**Backward compat**:
* :func:`check_tool_with_policy` is NEW, opt-in.
* :class:`CapabilityGate.check` unchanged.
* :func:`enforce_tool_policy` unchanged.
* Pre-S79 callers (capability only OR tools only) continue to work.

**Migration path**:
* Phase 1 (S79): add :func:`check_tool_with_policy` to :class:`AIGateway`
  invoke path (S79 W3).
* Phase 2 (S79+ future): plugin authors migrate to
  :func:`check_tool_with_policy` for both-layer enforcement.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import TYPE_CHECKING

from src.backend.core.logging import get_logger
from src.backend.core.security.capabilities.errors import (
    CapabilityDeniedError,
)
from src.backend.core.ai.policy.enforcer.tools_policy import (
    ToolPolicyViolationError,
    check_tool_allowed,
    enforce_tool_policy,
)

if TYPE_CHECKING:
    from src.backend.core.security.capabilities.gate import (
        CapabilityGate,
    )
    from src.backend.core.ai.policy.spec import ToolsSpec

_logger = get_logger("core.security.capabilities.tool_integration")

__all__ = (
    "check_tool_with_policy",
    "filter_tools_with_gate",
    "ToolCapabilityCheckError",
)


class ToolCapabilityCheckError(PermissionError):
    """S79 W1 — combined error для tool call failures.

    Distinct от :exc:`CapabilityDeniedError` (capability layer only)
    and :exc:`ToolPolicyViolationError` (policy layer only). This
    exception wraps BOTH possibilities под unified error type,
    с ``reason`` attribute для diagnostics.
    """


def check_tool_with_policy(
    *,
    gate: "CapabilityGate",
    plugin: str,
    tool_name: str,
    scope: str | None,
    policy: "ToolsSpec",
) -> None:
    """Two-layer tool call enforcement (S79 W1).

    Combines :class:`CapabilityGate.check` (capability declared) +
    :func:`enforce_tool_policy` (AIPolicySpec.tools whitelist/blacklist).

    Args:
        gate: :class:`CapabilityGate` instance.
        plugin: plugin name (e.g. ``"credit_check"``).
        tool_name: tool name (e.g. ``"db.read.orders"``).
        scope: optional scope (e.g. ``"tenant_abc"``).
        policy: :class:`ToolsSpec` (AIPolicySpec.tools section).

    Raises:
        CapabilityDeniedError: capability layer failed (S36/S54).
        ToolPolicyViolationError: policy layer failed (S76).
        ToolCapabilityCheckError: wrapper для unified error
            reporting (если caller wants single error type).

    Examples:
        >>> gate = CapabilityGate()
        >>> gate.declare("credit", [CapabilityRef("db.read.orders")])
        >>> policy = ToolsSpec(whitelist=["db.read.orders"])
        >>> check_tool_with_policy(
        ...     gate=gate, plugin="credit",
        ...     tool_name="db.read.orders", scope=None,
        ...     policy=policy,
        ... )
        # OK: capability declared + in whitelist
    """
    # Layer 1: CapabilityGate (S36/S54)
    try:
        gate.check(plugin, tool_name, scope)
    except CapabilityDeniedError as exc:
        _logger.warning(
            "CapabilityGate denied tool=%s for plugin=%s: %s",
            tool_name,
            plugin,
            exc,
        )
        raise

    # Layer 2: AIPolicySpec.tools (S76 W2)
    try:
        enforce_tool_policy(tool_name, policy)
    except ToolPolicyViolationError as exc:
        _logger.warning(
            "AIPolicySpec.tools denied tool=%s for plugin=%s: %s",
            tool_name,
            plugin,
            exc,
        )
        raise


def filter_tools_with_gate(
    *,
    gate: "CapabilityGate",
    plugin: str,
    tool_names: Iterable[str],
    scope: str | None,
    policy: "ToolsSpec",
) -> list[str]:
    """S79 W3 — pre-init filter tool list через two-layer enforcement.

    Combines :class:`CapabilityGate.check` (capability declared) +
    :func:`check_tool_allowed` (AIPolicySpec.tools whitelist/blacklist).
    Returns list of tools that pass BOTH layers. Failed tools are
    silently dropped (с warning log) — caller НЕ получает per-tool
    exception (use :func:`check_tool_with_policy` для per-tool errors).

    Args:
        gate: :class:`CapabilityGate` instance.
        plugin: plugin name (e.g. ``"credit_check"``).
        tool_names: iterable of tool names (e.g. AgentSpec.tools).
        scope: optional scope (e.g. ``"tenant_abc"``).
        policy: :class:`ToolsSpec` (AIPolicySpec.tools section).

    Returns:
        Filtered list of tools that pass BOTH layers. Order preserved.

    Use case (S79 W3 integration):
        :class:`AgentSpec` constructor filters \`tools\` tuple через
        эту функцию. Результат — AgentSpec создаётся с filtered
        tools (fail-closed defense: agent НИКОГДА не получает
        disallowed tools в свой toolset).

        Pre-init filter (W3 approach) — alternative к per-invoke
        :func:`check_tool_with_policy` (W2). Оба approaches
        valid: pre-init for fail-closed, per-invoke для
        dynamic policy (hot-reload changes).

    Example:
        >>> gate = CapabilityGate()
        >>> gate.declare("credit", [
        ...     CapabilityRef("db.read.orders"),
        ...     CapabilityRef("ai.invoke.credit_check"),
        ... ])
        >>> policy = ToolsSpec(whitelist=["db.read.orders"])
        >>> filter_tools_with_gate(
        ...     gate=gate, plugin="credit",
        ...     tool_names=["db.read.orders", "ai.invoke.credit_check"],
        ...     scope=None, policy=policy,
        ... )
        ['db.read.orders']  # ai.invoke.credit_check dropped (not in whitelist)
    """
    allowed: list[str] = []
    for tool_name in tool_names:
        # Layer 1: CapabilityGate
        try:
            gate.check(plugin, tool_name, scope)
        except CapabilityDeniedError as exc:
            _logger.debug(
                "CapabilityGate dropped tool=%s for plugin=%s: %s",
                tool_name,
                plugin,
                exc,
            )
            continue
        # Layer 2: AIPolicySpec.tools
        if not check_tool_allowed(tool_name, policy):
            _logger.debug(
                "AIPolicySpec.tools dropped tool=%s for plugin=%s",
                tool_name,
                plugin,
            )
            continue
        allowed.append(tool_name)
    return allowed
