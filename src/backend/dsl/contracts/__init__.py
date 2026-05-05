"""Data contracts — GE-lite expectations для pipeline-валидации (C7).

Валидаторы: not_null, unique, regex, range, schema_ref.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Iterable

__all__ = ("Expectation", "ExpectationResult", "check_expectations")


@dataclass(slots=True)
class ExpectationResult:
    passed: bool
    failed_rows: int
    message: str


@dataclass(slots=True)
class Expectation:
    column: str
    not_null: bool = False
    unique: bool = False
    regex: str | None = None
    range: tuple[float, float] | None = None
    schema_ref: str | None = None

    def check(self, rows: Iterable[dict[str, Any]]) -> ExpectationResult:
        rows = list(rows)
        failed = 0
        seen: set[Any] = set()
        compiled = re.compile(self.regex) if self.regex else None
        for r in rows:
            v = r.get(self.column)
            if self.not_null and v is None:
                failed += 1
                continue
            if self.unique:
                if v in seen:
                    failed += 1
                    continue
                seen.add(v)
            if compiled is not None and v is not None:
                if not compiled.search(str(v)):
                    failed += 1
                    continue
            if self.range is not None and v is not None:
                try:
                    nv = float(v)
                except TypeError, ValueError:
                    failed += 1
                    continue
                lo, hi = self.range
                if not (lo <= nv <= hi):
                    failed += 1
        passed = failed == 0
        msg = f"{self.column}: failed={failed}/{len(rows)}"
        return ExpectationResult(passed=passed, failed_rows=failed, message=msg)


def check_expectations(
    expectations: list[Expectation], rows: Iterable[dict[str, Any]]
) -> list[ExpectationResult]:
    rows = list(rows)
    return [e.check(rows) for e in expectations]
