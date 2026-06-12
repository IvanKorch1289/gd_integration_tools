"""S76 W2 (FINAL_REPORT_V2 P0-B) — ToolsSpec enforcement.

``AIPolicySpec.tools`` (S76 W1) defines whitelist/blacklist +
``on_violation`` behavior. This module implements the enforcement
logic — invoked from AIGateway before tool dispatch.

**Enforcement** (3 modes):
* ``"fail"`` — raise :exc:`ToolPolicyViolationError` (default).
  Caller получает exception, может retry / log / handle.
* ``"warn"`` — log warning, allow invocation. Use case: dev/staging
  where policies are experimental.
* ``"block"`` — silently drop invocation. Use case: production
  defense-in-depth (without explicit error to caller).

**Validation** (S76 W2):
* ``check_tool_allowed(tool_name, spec)`` → bool
* ``enforce_tool_policy(tool_name, spec)`` → raise/warn/block per spec

**Integration** (S76 W3): AIGateway / PydanticAI agent tool dispatch
calls ``enforce_tool_policy(tool_name, current_policy)`` before invoke.

**Backward compat**: если ``spec.tools.whitelist`` и
``spec.tools.blacklist`` оба empty — все tools allowed (no restriction).
Pre-S76 YAML не имел ``tools`` секции → default ToolsSpec → all allowed.
"""

from __future__ import annotations

from collections.abc import Iterable
from typing import TYPE_CHECKING

from src.backend.core.logging import get_logger

if TYPE_CHECKING:
    from src.backend.core.ai.policy.spec import ToolsSpec


_logger = get_logger("core.ai.policy.tools")

__all__ = (
    "ToolPolicyViolationError",
    "check_tool_allowed",
    "enforce_tool_policy",
    "filter_tools_by_policy",
)


class ToolPolicyViolationError(PermissionError):
    """Raised when tool invocation violates AIPolicySpec.tools policy.

    Distinct from :exc:`GuardrailViolationError` (input/output content
    violations) — this is structural policy violation (tool not in
    whitelist / in blacklist).
    """


def check_tool_allowed(tool_name: str, spec: "ToolsSpec") -> bool:
    """Check if ``tool_name`` allowed per spec (no side effects).

    Returns:
        True если tool allowed (in whitelist или whitelist empty
        AND not in blacklist). False otherwise.

    Examples:
        >>> check_tool_allowed("db.read", ToolsSpec(whitelist=["db.*"]))
        True
        >>> check_tool_allowed("fs.write", ToolsSpec(blacklist=["fs.*"]))
        False
        >>> check_tool_allowed("any", ToolsSpec())  # default empty = allow
        True
    """
    # Blacklist — explicit denylist, applied regardless of whitelist
    if spec.blacklist and tool_name in spec.blacklist:
        return False

    # Whitelist — if non-empty, tool must be in it
    if spec.whitelist:
        return tool_name in spec.whitelist

    # No whitelist, no blacklist → allow all
    return True


def enforce_tool_policy(tool_name: str, spec: "ToolsSpec") -> None:
    """Enforce tool policy per spec.on_violation.

    Args:
        tool_name: tool being invoked.
        spec: AIPolicySpec.tools section.

    Raises:
        ToolPolicyViolationError: if tool not allowed AND
            on_violation == "fail".

    Side effects:
        * "warn": logs warning, allows invocation.
        * "block": silent drop (no log, no exception).
        * "fail": raises ToolPolicyViolationError.
    """
    if check_tool_allowed(tool_name, spec):
        return  # Tool allowed, no action

    # Tool violates policy — handle per on_violation
    if spec.on_violation == "fail":
        raise ToolPolicyViolationError(
            f"Tool {tool_name!r} violates AIPolicySpec.tools policy. "
            f"Whitelist={spec.whitelist}, Blacklist={spec.blacklist}."
        )
    elif spec.on_violation == "warn":
        _logger.warning(
            "Tool %r violates policy (whitelist=%s, blacklist=%s) — "
            "allowing invocation per on_violation=warn",
            tool_name,
            spec.whitelist,
            spec.blacklist,
        )
        return  # Allow
    elif spec.on_violation == "block":
        _logger.info(  # Use info (not warning) — silent per spec
            "Tool %r blocked per policy (whitelist=%s, blacklist=%s)",
            tool_name,
            spec.whitelist,
            spec.blacklist,
        )
        # Raise anyway — caller must handle (block = drop = no invoke)
        raise ToolPolicyViolationError(
            f"Tool {tool_name!r} blocked per policy (on_violation=block)"
        )
    else:
        # Defensive: unknown on_violation → fail (safe default)
        _logger.error(
            "Unknown on_violation=%r — defaulting to fail",
            spec.on_violation,
        )
        raise ToolPolicyViolationError(
            f"Tool {tool_name!r} blocked per policy (unknown on_violation)"
        )


def filter_tools_by_policy(
    tool_names: Iterable[str], spec: "ToolsSpec"
) -> list[str]:
    """Filter list of tool names per spec (whitelist/blacklist).

    Useful для AIGateway initialize: pre-compute allowed tool set,
    pass to PydanticAI agent's tools= argument.

    Args:
        tool_names: iterable of all available tool names.
        spec: AIPolicySpec.tools section.

    Returns:
        Filtered list (tools passing check_tool_allowed).
        Original order preserved.

    Note: ``on_violation`` NOT applied here (this is filter, not
    enforcement). Caller decides whether to fail on filtered-out
    tools (typically: silent if filter is pre-init, loud if filter
    is per-invoke).

    Examples:
        >>> filter_tools_by_policy(["db.read", "fs.write", "ai.invoke"],
        ...                        ToolsSpec(blacklist=["fs.*"]))
        ['db.read', 'ai.invoke']
    """
    return [name for name in tool_names if check_tool_allowed(name, spec)]
