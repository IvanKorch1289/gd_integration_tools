"""AST gate: запрет high-cardinality Prometheus labels (audit W9).

Per audit W9: «Запретить tenant_id, user_id, raw route parameters
и schedule UUID как Prometheus labels. Их можно помещать в traces/logs
с policy-controlled hashing. Добавить cardinality test и budget на
unique label values».

Проблема: ``.labels(tenant_id=...)`` создаёт одну time-series per tenant.
При 10000 tenants → 10000 time-series per metric → memory/storage
explosion в Prometheus. Корректные места для high-cardinality data —
traces (sampled) и logs (queryable), но не metrics (raw counts).

Audit rules:
- FORBIDDEN labels (high-cardinality): ``tenant_id``, ``user_id``,
  ``schedule_id``, ``workflow_id``, ``request_id``, ``correlation_id``
  (UUIDs, raw identifiers);
- ALLOWED labels (low-cardinality): ``status``, ``route``, ``pool``,
  ``backend``, ``status_code``, ``pool_name``, ``method``, ``endpoint``.
- Uncertain labels (route_id, step, action) — flagged как WARNING
  (может быть high-cardinality, зависит от cardinalности).

Gate strategy:
- Baseline фиксирует текущие labels (для backward compat);
- --strict FAILs на NEW FORBIDDEN labels;
- WARNING labels — логируются но НЕ блокируют;
- --json output для machine-readable integration.
"""

from __future__ import annotations

import argparse
import ast
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SRC_ROOT = PROJECT_ROOT / "src" / "backend"
BASELINE_PATH = (
    PROJECT_ROOT / ".baselines" / "high_cardinality_metrics_baseline.json"
)

# Per audit W9: forbidden (high-cardinality) labels.
FORBIDDEN_LABELS: frozenset[str] = frozenset(
    {
        "tenant_id",
        "user_id",
        "schedule_id",
        "workflow_id",
        "request_id",
        "correlation_id",
        "trace_id",
        "span_id",
        "session_id",
    }
)

# Low-cardinality (allowed): not flagged.
ALLOWED_LABELS: frozenset[str] = frozenset(
    {
        "status",
        "route",
        "pool",
        "backend",
        "method",
        "endpoint",
        "stage",
        "kind",
        "type",
        "code",
        "name",
        "operation",
        "tool",
        "pool_name",
        "metric",
    }
)


def _scan_metric_labels(file: Path) -> list[dict]:
    """Scan ``file`` for ``.labels(tenant_id=...)`` etc.

    Returns:
        List of ``{file, line, full_call, forbidden_label, severity}`` dicts.
    """
    findings: list[dict] = []
    try:
        content = file.read_text(encoding="utf-8", errors="ignore")
        tree = ast.parse(content)
    except SyntaxError:
        return findings

    rel = str(file.resolve().relative_to(PROJECT_ROOT.resolve()))

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        # Detect ``<obj>.labels(...)`` calls.
        if not (
            isinstance(node.func, ast.Attribute)
            and node.func.attr == "labels"
        ):
            continue

        # Process keyword arguments of .labels().
        # Note: kw.value может быть ast.Constant (literal) или ast.Name
        # (variable reference like ``tenant_id=tenant_label``). Для detection
        # нам важен только label NAME (kw.arg), не value source.
        for kw in node.keywords:
            label_name = kw.arg
            # Skip dynamic labels (``**labels`` → kw.arg is None) and
            # empty labels (None arg).
            if not label_name or not isinstance(label_name, str):
                continue
            if label_name in FORBIDDEN_LABELS:
                findings.append(
                    {
                        "file": rel,
                        "line": node.lineno,
                        "full_call": ast.unparse(node)[:200],
                        "label": label_name,
                        "severity": "FORBIDDEN",
                        "reason": (
                            f"label {label_name!r} is high-cardinality "
                            f"(per-tenant/per-user/per-request). "
                            f"Per audit W9: «Запретить tenant_id, user_id, raw "
                            f"route parameters как Prometheus labels. Их можно "
                            f"помещать в traces/logs с policy-controlled hashing»."
                        ),
                    }
                )
            elif label_name not in ALLOWED_LABELS and label_name not in FORBIDDEN_LABELS:
                # Unknown label — heuristic warning.
                findings.append(
                    {
                        "file": rel,
                        "line": node.lineno,
                        "full_call": ast.unparse(node)[:200],
                        "label": label_name,
                        "severity": "WARNING",
                        "reason": (
                            f"label {label_name!r} — verify cardinality. "
                            f"If high (per-tenant, per-user), move to traces/logs."
                        ),
                    }
                )

    return findings


def _collect_all_findings() -> list[dict]:
    findings: list[dict] = []
    for py in SRC_ROOT.rglob("*.py"):
        if "__pycache__" in py.parts:
            continue
        if "/tests/" in str(py) or "/examples/" in str(py):
            continue
        findings.extend(_scan_metric_labels(py.resolve()))
    return findings


def _read_baseline() -> list[dict] | None:
    if not BASELINE_PATH.is_file():
        return None
    try:
        return json.loads(BASELINE_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def _write_baseline(findings: list[dict]) -> None:
    BASELINE_PATH.parent.mkdir(parents=True, exist_ok=True)
    BASELINE_PATH.write_text(
        json.dumps(findings, indent=2, ensure_ascii=False, sort_keys=True),
        encoding="utf-8",
    )


def _finding_key(f: dict) -> tuple:
    """Stable key для drift detection."""
    return (f["file"], f["line"], f["label"])


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "AST gate: запрет high-cardinality Prometheus labels. "
            "Per audit W9: «Запретить tenant_id, user_id, raw route "
            "parameters как Prometheus labels»."
        )
    )
    parser.add_argument(
        "--strict", action="store_true", help="Exit 1 на NEW FORBIDDEN labels."
    )
    parser.add_argument("--json", action="store_true", help="JSON output.")
    parser.add_argument(
        "--update-baseline",
        action="store_true",
        help="Обновить baseline (для intentional refactors).",
    )
    args = parser.parse_args(argv)

    current = _collect_all_findings()
    forbidden_current = [f for f in current if f["severity"] == "FORBIDDEN"]
    warning_current = [f for f in current if f["severity"] == "WARNING"]

    if args.update_baseline:
        _write_baseline(current)
        sys.stdout.write(
            f"✅ Baseline обновлён: {len(forbidden_current)} FORBIDDEN + "
            f"{len(warning_current)} WARNING labels.\n"
            f"  Файл: {BASELINE_PATH.relative_to(PROJECT_ROOT)}\n"
        )
        return 0

    baseline = _read_baseline()

    if baseline is None:
        _write_baseline(current)
        sys.stdout.write(
            f"⚠️  Baseline создан ({len(forbidden_current)} FORBIDDEN + "
            f"{len(warning_current)} WARNING labels).\n"
        )
        if args.json:
            sys.stdout.write(
                json.dumps(
                    {
                        "baseline_established": True,
                        "forbidden_count": len(forbidden_current),
                        "warning_count": len(warning_current),
                        "findings": current,
                    },
                    indent=2,
                    ensure_ascii=False,
                )
                + "\n"
            )
        return 0

    # Compare.
    baseline_forbidden_keys = {
        _finding_key(f)
        for f in baseline
        if f["severity"] == "FORBIDDEN"
    }
    current_forbidden_keys = {
        _finding_key(f) for f in forbidden_current
    }
    new_forbidden = current_forbidden_keys - baseline_forbidden_keys
    removed_forbidden = baseline_forbidden_keys - current_forbidden_keys

    if args.json:
        sys.stdout.write(
            json.dumps(
                {
                    "forbidden_baseline_count": len(baseline_forbidden_keys),
                    "forbidden_current_count": len(current_forbidden_keys),
                    "new_forbidden": sorted(new_forbidden),
                    "removed_forbidden": sorted(removed_forbidden),
                    "warning_count": len(warning_current),
                    "status": "FAIL" if new_forbidden else "PASS",
                },
                indent=2,
                ensure_ascii=False,
            )
            + "\n"
        )
    else:
        sys.stdout.write(
            f"High-cardinality metrics AST gate (audit W9)\n"
            f"  FORBIDDEN baseline: {len(baseline_forbidden_keys)}\n"
            f"  FORBIDDEN current:  {len(current_forbidden_keys)}\n"
            f"  WARNING current:    {len(warning_current)}\n"
        )
        if new_forbidden:
            sys.stdout.write(
                "\n  ❌ NEW FORBIDDEN labels (need fix или baseline update):\n"
            )
            for f in sorted(new_forbidden):
                sys.stdout.write(f"    - {f}\n")
        if warning_current:
            sys.stdout.write(
                f"\n  ⚠️  WARNING labels (verify cardinality, not blocking):\n"
            )
            for f in warning_current[:10]:
                sys.stdout.write(
                    f"    - {f['file']}:{f['line']} {f['label']}\n"
                )
        if not new_forbidden and not warning_current:
            sys.stdout.write("\n  ✅ No high-cardinality metric labels\n")

    if args.strict and new_forbidden:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
