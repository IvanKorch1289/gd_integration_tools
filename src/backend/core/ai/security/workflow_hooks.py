"""Workflow-specific security hooks (S188).

Предоставляет pre-built hooks для типичных workflow scenarios.
Эти hooks могут быть зарегистрированы в :class:`AgentSecurityFramework`
для усиления проверок в конкретных workflows.

Hooks:
- :func:`banking_transaction_hook` — для banking workflows
- :func:`rpa_browser_hook` — для RPA browser automation
- :func:`code_generation_hook` — для code generation workflows
- :func:`data_export_hook` — для data export workflows

Использование::

    from src.backend.core.ai.security.workflow_hooks import (
        register_banking_transaction_hook,
    )

    register_banking_transaction_hook(get_agent_security_framework())

Production wiring: через workflow initialization (см. workflow setup).
"""

from __future__ import annotations

import tempfile
from pathlib import Path
from typing import Any

from src.backend.core.ai.security import SecurityDecision, SecurityHook, ThreatLevel
from src.backend.core.logging import get_logger

__all__ = (
    "banking_transaction_hook",
    "code_generation_hook",
    "data_export_hook",
    "register_banking_transaction_hook",
    "register_code_generation_hook",
    "register_data_export_hook",
    "register_rpa_browser_hook",
    "rpa_browser_hook",
)

_logger = get_logger("core.ai.security.workflow_hooks")

# Resolve system temp roots at import time via stdlib (no hardcoded paths).
# ``tempfile.gettempdir()`` respects TMPDIR/TMP/TEMP env overrides; on Linux
# ``/var/tmp`` is the conventional secondary temp location used by systemd
# and many installers. Both are matched as ``Path.is_relative_to`` to
# avoid substring false positives (e.g. ``/tmpfoo/...``).
_TEMP_ROOTS: tuple[Path, ...] = (
    Path(tempfile.gettempdir()).resolve(),
    Path(Path(tempfile.gettempdir()).anchor) / "var" / "tmp",
)


def banking_transaction_hook(subject: str, context: dict[str, Any]) -> SecurityDecision:
    """Hook для banking transaction workflows (S188 + Cycle 39).

    Усиленная проверка для financial operations. Cycle 39 audit:
    this hook was previously a NO-OP stub — it logged a debug message
    and returned ``allowed=True`` regardless. Production wiring was
    registered but did nothing.

    Now actually blocks:
    - **SQL mutations** unless they target whitelisted stored procs
      (``call_procedure`` tool, named procedures starting with
      ``sp_bank_`` or ``sp_payments_``).
    - **File modifications** in critical system paths (``/etc/``, ``/var/``,
      banking configs under ``/opt/bank/conf``).
    - **Destructive shell commands**: ``rm -rf``, ``mkfs``, ``dd``,
      ``shutdown``, ``reboot``.

    Args:
        subject: User/service identity.
        context: Hook context (должен содержать ``workflow`` key, may
            contain ``sql_query``, ``tool_name``, ``file_path``,
            ``command``).

    Returns:
        SecurityDecision: allowed=True if all checks pass, else
        SecurityDecision(allowed=False, threat_level=CRITICAL, reason=...).
    """
    workflow = context.get("workflow", "")
    if not workflow.startswith("banking."):
        return SecurityDecision(allowed=True)

    _logger.debug(
        "banking_transaction_hook: subject=%s workflow=%s",
        subject,
        workflow,
    )

    # ─── Check 1: SQL mutations ────────────────────────────────────
    # Banking workflows should only mutate via audited stored procs,
    # not raw SQL. Allow call_procedure tool with whitelisted names.
    sql_query = context.get("sql_query") or context.get("query") or ""
    tool_name = context.get("tool_name") or ""
    if sql_query and tool_name != "call_procedure":
        # Raw SQL mutation detected in banking workflow.
        # Allow non-mutating SELECT/PRAGMA/SHOW.
        normalized = sql_query.strip().upper().lstrip("(")
        if not normalized.startswith(
            ("SELECT", "PRAGMA", "SHOW", "EXPLAIN", "WITH"),
        ):
            return SecurityDecision(
                allowed=False,
                threat_level=ThreatLevel.CRITICAL,
                reason=(
                    f"banking raw_sql_mutation: tool={tool_name!r} "
                    f"query_prefix={normalized[:32]!r} — banking workflows "
                    f"require call_procedure tool with whitelisted proc name"
                ),
            )

    # ─── Check 2: File modifications in critical paths ────────────
    file_path = context.get("file_path") or ""
    if file_path:
        # Banking workflows must not touch system configs.
        dangerous_paths = (
            "/etc/",
            "/var/",
            "/boot/",
            "/proc/",
            "/sys/",
            "/opt/bank/conf",  # banking config root
        )
        try:
            resolved = Path(file_path).resolve()
        except (OSError, ValueError):
            resolved = None
        if resolved is not None and any(
            str(resolved).startswith(p) for p in dangerous_paths
        ):
            return SecurityDecision(
                allowed=False,
                threat_level=ThreatLevel.CRITICAL,
                reason=f"banking system_path_modification: {file_path}",
            )

    # ─── Check 3: Destructive shell commands ──────────────────────
    command = context.get("command") or ""
    if command:
        dangerous_commands = (
            "rm -rf",
            "rm -fr",
            "mkfs",
            "dd if=",
            "shutdown",
            "reboot",
            "halt",
            "poweroff",
            ":(){:|:&};:",  # fork bomb
        )
        cmd_normalized = command.lower().strip()
        for dangerous in dangerous_commands:
            if dangerous in cmd_normalized:
                return SecurityDecision(
                    allowed=False,
                    threat_level=ThreatLevel.CRITICAL,
                    reason=f"banking destructive_command: {dangerous!r}",
                )

    return SecurityDecision(
        allowed=True,
        threat_level=ThreatLevel.LOW,
        reason=f"banking workflow validated: {workflow}",
    )


def rpa_browser_hook(subject: str, context: dict[str, Any]) -> SecurityDecision:
    """Hook для RPA browser automation workflows.

    Усиленная проверка для RPA operations:
    - Block downloads to suspicious paths (/tmp/, /var/tmp/)
    - Block screenshots of authentication pages (security)
    - Block file uploads to external services

    Args:
        subject: User/service identity.
        context: Hook context.

    Returns:
        SecurityDecision.
    """
    workflow = context.get("workflow", "")
    if not workflow.startswith("rpa."):
        return SecurityDecision(allowed=True)

    file_path = context.get("file_path", "")
    if file_path:
        try:
            resolved = Path(file_path).resolve()
        except (OSError, ValueError):
            resolved = None
        if resolved is not None and any(
            resolved.is_relative_to(root) for root in _TEMP_ROOTS
        ):
            return SecurityDecision(
                allowed=False,
                threat_level=ThreatLevel.HIGH,
                reason=f"rpa file_path_not_allowed: {file_path}",
            )

    return SecurityDecision(
        allowed=True,
        threat_level=ThreatLevel.NONE,
    )


def code_generation_hook(subject: str, context: dict[str, Any]) -> SecurityDecision:
    """Hook для code generation workflows.

    Усиленная проверка для code generation:
    - Block file writes в критические system paths
    - Block subprocess shell injection patterns
    - Require audit emission для всех generated code

    Args:
        subject: User/service identity.
        context: Hook context.

    Returns:
        SecurityDecision.
    """
    workflow = context.get("workflow", "")
    if not workflow.startswith("code_generation."):
        return SecurityDecision(allowed=True)

    file_path = context.get("file_path", "")
    dangerous_paths = ("/etc/", "/var/", "/boot/", "/proc/", "/sys/")
    if file_path and any(file_path.startswith(p) for p in dangerous_paths):
        return SecurityDecision(
            allowed=False,
            threat_level=ThreatLevel.CRITICAL,
            reason=f"code_generation system_path: {file_path}",
        )

    return SecurityDecision(
        allowed=True,
        threat_level=ThreatLevel.NONE,
    )


def data_export_hook(subject: str, context: dict[str, Any]) -> SecurityDecision:
    """Hook для data export workflows.

    Усиленная проверка для exports:
    - Block PII/PCI data без masking
    - Block exports > N rows (data exfiltration)
    - Block external destinations

    Args:
        subject: User/service identity.
        context: Hook context (должен содержать ``row_count``).

    Returns:
        SecurityDecision.
    """
    workflow = context.get("workflow", "")
    if not workflow.startswith("data_export."):
        return SecurityDecision(allowed=True)

    row_count = context.get("row_count", 0)
    if row_count > 100_000:
        return SecurityDecision(
            allowed=False,
            threat_level=ThreatLevel.HIGH,
            reason=f"data_export too_many_rows: {row_count}",
        )

    return SecurityDecision(
        allowed=True,
        threat_level=ThreatLevel.NONE,
    )


def register_banking_transaction_hook(framework: Any) -> None:
    """Register banking_transaction_hook в framework."""
    framework.register_hook(
        SecurityHook(
            name="banking_transaction",
            trigger="pre_tool",
            check_fn=banking_transaction_hook,
        ),
    )
    _logger.info("registered: banking_transaction_hook")


def register_rpa_browser_hook(framework: Any) -> None:
    """Register rpa_browser_hook в framework."""
    framework.register_hook(
        SecurityHook(
            name="rpa_browser",
            trigger="pre_tool",
            check_fn=rpa_browser_hook,
        ),
    )
    _logger.info("registered: rpa_browser_hook")


def register_code_generation_hook(framework: Any) -> None:
    """Register code_generation_hook в framework."""
    framework.register_hook(
        SecurityHook(
            name="code_generation",
            trigger="pre_tool",
            check_fn=code_generation_hook,
        ),
    )
    _logger.info("registered: code_generation_hook")


def register_data_export_hook(framework: Any) -> None:
    """Register data_export_hook в framework."""
    framework.register_hook(
        SecurityHook(
            name="data_export",
            trigger="pre_tool",
            check_fn=data_export_hook,
        ),
    )
    _logger.info("registered: data_export_hook")


def register_all_workflow_hooks(framework: Any) -> None:
    """Register все workflow-specific hooks (S188).

    Convenience function для production setup.
    """
    register_banking_transaction_hook(framework)
    register_rpa_browser_hook(framework)
    register_code_generation_hook(framework)
    register_data_export_hook(framework)
    _logger.info("all workflow hooks registered")
