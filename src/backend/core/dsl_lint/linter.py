"""DSLLinter — static analyzer для route configs (Wave 2 DX #28)."""

from __future__ import annotations

import enum
import re
from dataclasses import dataclass, field
from typing import Any

logger = __import__("logging").getLogger(__name__)

__all__ = ("DSLLinter", "LintResult", "LintSeverity", "LintViolation", "get_dsl_linter")


class LintSeverity(str, enum.Enum):
    """Severity уровень violation."""

    ERROR = "error"  # блокирует deploy
    WARNING = "warning"  # рекомендация
    INFO = "info"  # informational


@dataclass(slots=True)
class LintViolation:
    """Single lint violation."""

    rule_id: str
    severity: LintSeverity
    message: str
    line: int | None = None
    column: int | None = None


@dataclass(slots=True)
class LintResult:
    """Result of linting одной route."""

    route_id: str
    violations: list[LintViolation] = field(default_factory=list)

    @property
    def has_errors(self) -> bool:
        return any(v.severity == LintSeverity.ERROR for v in self.violations)

    @property
    def error_count(self) -> int:
        return sum(1 for v in self.violations if v.severity == LintSeverity.ERROR)

    @property
    def warning_count(self) -> int:
        return sum(
            1 for v in self.violations if v.severity == LintSeverity.WARNING
        )


class DSLLinter:
    """DSL static analyzer."""

    def __init__(self) -> None:
        pass

    def lint_route(self, route_config: dict[str, Any]) -> LintResult:
        """Lint one route config.

        Args:
            route_config: Parsed route.toml как dict (или dsl.yaml).

        Returns:
            :class:`LintResult` с violations.

        """
        route_id = route_config.get("id", "<unknown>")
        result = LintResult(route_id=route_id)
        contract = route_config.get("contract", {})
        security = route_config.get("security", {})

        # L007: owner required.
        if not route_config.get("owner"):
            result.violations.append(
                LintViolation(
                    rule_id="L007",
                    severity=LintSeverity.ERROR,
                    message="Route must have 'owner' field (no orphan routes)",
                )
            )

        # L001: timeout required.
        timeout = contract.get("timeout_seconds")
        if timeout is None:
            result.violations.append(
                LintViolation(
                    rule_id="L001",
                    severity=LintSeverity.ERROR,
                    message="Route must have contract.timeout_seconds",
                )
            )
        elif isinstance(timeout, (int, float)):
            if timeout <= 0:
                result.violations.append(
                    LintViolation(
                        rule_id="L001",
                        severity=LintSeverity.ERROR,
                        message=f"timeout_seconds must be > 0 (got {timeout})",
                    )
                )
            elif timeout > 300:
                result.violations.append(
                    LintViolation(
                        rule_id="L005",
                        severity=LintSeverity.WARNING,
                        message=f"timeout_seconds > 300 (got {timeout})",
                    )
                )

        # Detect writes from side_effects or sources.
        side_effects = self._detect_side_effects(route_config)
        has_writes = any(
            s in ("db_write", "mq_publish", "file_write", "external_call")
            for s in side_effects
        )

        # L002: idempotency required для writes.
        if has_writes and not contract.get("idempotency_key_field"):
            result.violations.append(
                LintViolation(
                    rule_id="L002",
                    severity=LintSeverity.ERROR,
                    message=(
                        "Write route must have contract.idempotency_key_field "
                        f"(side_effects={side_effects})"
                    ),
                )
            )

        # L003: DLQ topic recommended.
        if has_writes and not contract.get("dlq_topic"):
            result.violations.append(
                LintViolation(
                    rule_id="L003",
                    severity=LintSeverity.WARNING,
                    message="Write route should have contract.dlq_topic",
                )
            )

        # L004: PII policy для routes с PII fields.
        sensitive_fields = self._detect_sensitive_fields(route_config)
        if sensitive_fields and not security.get("pii_policy"):
            result.violations.append(
                LintViolation(
                    rule_id="L004",
                    severity=LintSeverity.WARNING,
                    message=(
                        f"Route handles sensitive fields {sensitive_fields} "
                        "but security.pii_policy is not set"
                    ),
                )
            )

        # L006: retry max_attempts sane.
        max_retries = contract.get("max_retries")
        if max_retries is not None and max_retries > 10:
            result.violations.append(
                LintViolation(
                    rule_id="L006",
                    severity=LintSeverity.WARNING,
                    message=f"max_retries > 10 (got {max_retries})",
                )
            )

        return result

    def _detect_side_effects(self, route_config: dict[str, Any]) -> list[str]:
        """Heuristic: detect side effects из source/tags."""
        effects = []
        source = route_config.get("source", "")
        if "timer:" in source or "action:" in source:
            effects.append("external_call")
        if "filewatcher:" in source:
            effects.append("file_write")
        if "cdc:" in source:
            effects.append("db_write")
        # Tags-based detection.
        tags = route_config.get("tags", [])
        if any("db" in t.lower() for t in tags):
            effects.append("db_write")
        if any("mq" in t.lower() or "publish" in t.lower() for t in tags):
            effects.append("mq_publish")
        return list(set(effects))

    def _detect_sensitive_fields(self, route_config: dict[str, Any]) -> list[str]:
        """Heuristic: detect sensitive fields (PII keywords)."""
        sensitive_keywords = {
            "ssn", "passport", "credit_card", "card_number",
            "email", "phone", "address", "dob", "birth_date",
        }
        found = []
        # Scan inputs.
        inputs = route_config.get("input_fields", [])
        for field in inputs:
            field_lower = field.lower()
            if any(kw in field_lower for kw in sensitive_keywords):
                found.append(field)
        # Scan description.
        description = route_config.get("description", "").lower()
        for kw in sensitive_keywords:
            if kw in description:
                found.append(kw)
                break
        return list(set(found))


_linter: DSLLinter | None = None


def get_dsl_linter() -> DSLLinter:
    global _linter
    if _linter is None:
        _linter = DSLLinter()
    return _linter


def reset_dsl_linter() -> None:
    global _linter
    _linter = None
