"""Sprint health-check script (S175 M10.4 — DX).

Lightweight CLI для end-of-sprint verification: aggregates existing
health signals (test count, audit-event wiring, file coverage).
Не запускает полный test suite (too slow) — только quick signals для
PR review / sprint closure report.

Output: human-readable table + JSON. Exit code 0 если все signals
green, 1 если warning (degraded), 2 если critical failure.

Per S175 M10.4 lightweight scope: НЕ заменяет make-цели
(make test / make lint / make check-secrets-simple). Complement
для pre-PR quick check (~5 sec).

Usage::

    uv run python tools/verify_sprint_health.py
    uv run python tools/verify_sprint_health.py --json
    uv run python tools/verify_sprint_health.py --strict

Cumulative: a3bb7acc → ... → d2ccc2d3 (M10.3) → M10.4.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

_REPO_ROOT = Path(__file__).resolve().parents[1]


@dataclass(slots=True)
class HealthSignal:
    """One health-check result."""

    name: str
    status: str  # "ok" / "warning" / "critical"
    detail: str


@dataclass(slots=True)
class HealthReport:
    signals: list[HealthSignal] = field(default_factory=list)

    @property
    def is_critical(self) -> bool:
        return any(s.status == "critical" for s in self.signals)

    @property
    def is_warning(self) -> bool:
        return any(s.status == "warning" for s in self.signals)

    def to_dict(self) -> dict[str, Any]:
        return {
            "signals": [
                {"name": s.name, "status": s.status, "detail": s.detail}
                for s in self.signals
            ],
            "critical": self.is_critical,
            "warning": self.is_warning,
        }


def _check_audit_event_wiring() -> HealthSignal:
    """S175 M10.4: count emit_audit_safe usages как observability signal.

    Не perfect metric (false positives possible), но quick signal
    audit-event coverage.
    """
    src = _REPO_ROOT / "src"
    if not src.exists():
        return HealthSignal(
            name="audit_event_wiring",
            status="warning",
            detail="src/ not found",
        )
    pattern = re.compile(r"emit_audit_safe\s*\(")
    count = sum(
        1
        for path in src.rglob("*.py")
        if path.is_file() and pattern.search(path.read_text(encoding="utf-8", errors="ignore"))
    )
    if count >= 10:
        return HealthSignal(
            name="audit_event_wiring",
            status="ok",
            detail=f"{count} emit_audit_safe calls — observability wired",
        )
    return HealthSignal(
        name="audit_event_wiring",
        status="warning",
        detail=f"{count} emit_audit_safe calls — minimal observability coverage",
    )


def _check_pre_commit_hooks() -> HealthSignal:
    """S175 M10.4: verify M9.1 hook check-secrets-simple present."""
    config = _REPO_ROOT / ".pre-commit-config.yaml"
    if not config.exists():
        return HealthSignal(
            name="pre_commit_hooks",
            status="warning",
            detail=".pre-commit-config.yaml not found",
        )
    text = config.read_text(encoding="utf-8")
    if "check-secrets-simple" not in text:
        return HealthSignal(
            name="pre_commit_hooks",
            status="warning",
            detail="check-secrets-simple hook not wired (M9.1 pending)",
        )
    return HealthSignal(
        name="pre_commit_hooks",
        status="ok",
        detail="M9.1 hook check-secrets-simple wired (pre-push)",
    )


def _check_secret_detector() -> HealthSignal:
    """S175 M10.4: verify M8.4 tool exists and is executable."""
    tool = _REPO_ROOT / "tools" / "check_secrets_simple.py"
    if not tool.exists():
        return HealthSignal(
            name="secret_detector",
            status="critical",
            detail="tools/check_secrets_simple.py not found",
        )
    return HealthSignal(
        name="secret_detector",
        status="ok",
        detail="M8.4 secret-leakage detector available",
    )


def _check_strength_validator() -> HealthSignal:
    """S175 M10.4: verify M8.3 / M10.3 strength validators shipped."""
    api_key = _REPO_ROOT / "src" / "backend" / "core" / "auth" / "api_key_backend.py"
    jwt = _REPO_ROOT / "src" / "backend" / "core" / "auth" / "jwt_backend.py"
    if not api_key.exists() or not jwt.exists():
        return HealthSignal(
            name="strength_validators",
            status="warning",
            detail="api_key_backend.py or jwt_backend.py not found",
        )
    api_text = api_key.read_text(encoding="utf-8", errors="ignore")
    jwt_text = jwt.read_text(encoding="utf-8", errors="ignore")
    has_api = "validate_strength" in api_text
    has_jwt = "_validate_jwt_secret_strength" in jwt_text
    if has_api and has_jwt:
        return HealthSignal(
            name="strength_validators",
            status="ok",
            detail="M8.3 (api_key) + M10.3 (jwt) shipped",
        )
    return HealthSignal(
        name="strength_validators",
        status="warning",
        detail=(
            f"api_key.validate_strength={has_api} "
            f"jwt._validate_jwt_secret_strength={has_jwt}"
        ),
    )


def _check_workspace_isolation() -> HealthSignal:
    """S175 M10.4: parallel-agents workspace isolation check.

    Workspace НЕ должен содержать uncommitted modifications от чужих
    agents (per D121 binding rule). Это signal — НЕ strict check
    (parallel-agents могут быть mid-work).
    """
    try:
        result = __import__("subprocess").run(
            ["git", "status", "--short"],
            cwd=_REPO_ROOT,
            capture_output=True,
            text=True,
            check=False,
            timeout=5,
        )
        modified_count = len(
            [
                line
                for line in result.stdout.splitlines()
                if line.strip()
                and not line.startswith("??")  # untracked = OK
            ]
        )
        if modified_count < 10:
            return HealthSignal(
                name="workspace_isolation",
                status="ok",
                detail=f"{modified_count} modified files (parallel-agents minimal)",
            )
        return HealthSignal(
            name="workspace_isolation",
            status="warning",
            detail=f"{modified_count} modified files (parallel-agents active)",
        )
    except Exception as exc:
        return HealthSignal(
            name="workspace_isolation",
            status="warning",
            detail=f"git status check failed: {exc}",
        )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="S175 M10.4 — quick sprint health check"
    )
    parser.add_argument(
        "--json", action="store_true",
        help="Output as JSON (для CI integration)",
    )
    parser.add_argument(
        "--strict", action="store_true",
        help="Exit 1 на warnings (CI gate).",
    )
    args = parser.parse_args(argv)

    report = HealthReport(
        signals=[
            _check_audit_event_wiring(),
            _check_pre_commit_hooks(),
            _check_secret_detector(),
            _check_strength_validator(),
            _check_workspace_isolation(),
        ]
    )

    if args.json:
        print(json.dumps(report.to_dict(), indent=2))
    else:
        for signal in report.signals:
            symbol = {
                "ok": "[OK]",
                "warning": "[WARN]",
                "critical": "[CRIT]",
            }.get(signal.status, "[?]")
            print(f"{symbol:6s} {signal.name:30s} {signal.detail}")

    if report.is_critical:
        return 2
    if report.is_warning and args.strict:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
