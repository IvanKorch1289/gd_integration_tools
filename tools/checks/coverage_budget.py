"""Coverage budget ratchet (Wave 4 P3.16).

Reads coverage data и enforces a minimum overall coverage threshold.

Ratchet policy:
- baseline stored in ``.baselines/coverage.json``.
- threshold can be ratcheted UP (improvement) but not DOWN.
- fails CI if current coverage < baseline.

Usage:
    python tools/checks/coverage_budget.py --min 60
    python tools/checks/coverage_budget.py --update-baseline
    python tools/checks/coverage_budget.py --report-only
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
BASELINE_FILE = PROJECT_ROOT / ".baselines" / "coverage.json"
COVERAGE_JSON = PROJECT_ROOT / "coverage.json"
COVERAGE_XML = PROJECT_ROOT / "coverage.xml"


def _read_baseline() -> float:
    """Read stored baseline coverage."""
    if not BASELINE_FILE.exists():
        return 0.0
    return float(BASELINE_FILE.read_text(encoding="utf-8").strip())


def _write_baseline(value: float) -> None:
    BASELINE_FILE.parent.mkdir(parents=True, exist_ok=True)
    BASELINE_FILE.write_text(f"{value}\n", encoding="utf-8")


def _read_current_coverage() -> float | None:
    """Read coverage from coverage.json or coverage.xml."""
    if COVERAGE_JSON.exists():
        try:
            data = json.loads(COVERAGE_JSON.read_text(encoding="utf-8"))
            return data.get("totals", {}).get("percent_covered", None)
        except Exception:  # broad — file may be malformed
            pass
    return None


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Coverage budget ratchet (Wave 4 P3.16)"
    )
    parser.add_argument(
        "--min",
        type=float,
        default=None,
        help="Minimum coverage percentage (overrides baseline)",
    )
    parser.add_argument(
        "--update-baseline",
        action="store_true",
        help="Update baseline to current coverage (ratchet up only)",
    )
    parser.add_argument(
        "--report-only",
        action="store_true",
        help="Print report but don't fail",
    )
    args = parser.parse_args()

    current = _read_current_coverage()
    baseline = _read_baseline()
    min_coverage = args.min if args.min is not None else baseline

    print("=" * 60)
    print("Coverage Budget Ratchet Report")
    print("=" * 60)
    print(f"Current coverage:  {current:.2f}%" if current else "Current coverage:  N/A")
    print(f"Baseline:         {baseline:.2f}%")
    print(f"Min required:      {min_coverage:.2f}%")
    print()

    if current is None:
        print("⚠ No coverage data found.")
        print("  Run: pytest --cov=src.backend --cov-report=json")
        return 1 if not args.report_only else 0

    if args.update_baseline:
        if current > baseline:
            _write_baseline(current)
            print(f"✓ Baseline ratcheted UP: {baseline:.2f}% → {current:.2f}%")
            return 0
        else:
            print(
                f"✗ Baseline can only ratchet UP. "
                f"Current {current:.2f}% ≤ baseline {baseline:.2f}%."
            )
            return 1

    if current < min_coverage:
        print(
            f"✗ FAIL: coverage {current:.2f}% < min {min_coverage:.2f}%"
        )
        return 1 if not args.report_only else 0
    print(f"✓ PASS: coverage {current:.2f}% ≥ min {min_coverage:.2f}%")
    return 0


def cli() -> None:
    """CLI entry point that always exits with status code."""
    result = main()
    sys.exit(result)


if __name__ == "__main__":
    cli()
