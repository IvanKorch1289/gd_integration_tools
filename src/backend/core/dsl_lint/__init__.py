"""DSL Lint — static analysis для DSL routes (Wave 2 DX #28).

Проблема (EP-R1):
    Ошибки в DSL выявляются только при runtime:
    - Отсутствует timeout → request hangs forever.
    - Нет idempotency для write-route → дубли.
    - Нет DLQ → poison message блокирует queue.
    - Нет PII policy → sensitive data утекает.

Решение:
    ``DSLLinter`` — static analyzer для route.toml + dsl.yaml:

    Rules:
    - L001: route без timeout → ERROR.
    - L002: write-route без idempotency_key_field → ERROR.
    - L003: route без DLQ topic → WARNING.
    - L004: route с sensitive fields без PII policy → WARNING.
    - L005: timeout > 300s → WARNING.
    - L006: retry max_attempts > 10 → WARNING.
    - L007: route без owner → ERROR (orphan route).

    ``lint_route(content)`` → ``LintResult`` с violations list.
"""

from __future__ import annotations

from src.backend.core.dsl_lint.linter import (
    DSLLinter,
    LintResult,
    LintSeverity,
    LintViolation,
    get_dsl_linter,
)

__all__ = (
    "DSLLinter",
    "LintResult",
    "LintSeverity",
    "LintViolation",
    "get_dsl_linter",
)
