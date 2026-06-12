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

from typing import TYPE_CHECKING

from src.backend.core.logging import get_logger
from src.backend.core.security.capabilities.errors import (
    CapabilityDeniedError,
)
from src.backend.core.ai.policy.enforcer.tools_policy import (
    ToolPolicyViolationError,
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
