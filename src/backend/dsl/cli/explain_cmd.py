"""DSL CLI: gd route explain — структурный analysis route.

Per 25.09 audit #9: «Реализовать DSL explain/replay MVP».

Usage::

    python -m src.backend.dsl.cli explain <route_dir>
    python -m src.backend.dsl.cli explain <route_dir> --json

Output: human-readable summary или JSON с graph + side effects + capabilities.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from src.backend.dsl.cli.explanation import explain_route


def _print_human(explanation_dict: dict) -> str:
    """Human-readable summary для terminal output."""
    lines = [
        f"Route: {explanation_dict['route_id']}",
        f"Directory: {explanation_dict['route_dir']}",
        f"Tenant-aware: {explanation_dict['tenant_aware']}",
        f"Timeout budget: {explanation_dict['timeout_ms']}ms",
        f"Total estimated duration: {explanation_dict['total_estimated_duration_ms']}ms",
        "",
        f"Steps ({len(explanation_dict['steps'])}):",
    ]
    for step in explanation_dict["steps"]:
        retry_info = f" [retry: {step['retry']['attempts']}x {step['retry']['backoff']}]" if step["retry"] else ""
        caps_str = ", ".join(step["capabilities_required"]) if step["capabilities_required"] else "—"
        lines.append(
            f"  [{step['index']:>2}] {step['step_type']:<20} "
            f"caps=[{caps_str}] est={step['estimated_duration_ms']}ms{retry_info}"
        )
        for se in step["side_effects"]:
            target_info = f" → {se['target']}" if se["target"] else ""
            lines.append(f"        ↳ {se['kind']}.{se['capability']}{target_info}")

    lines.append("")
    lines.append("Capabilities:")
    lines.append(
        f"  required: {', '.join(explanation_dict['capabilities_required']) or '—'}"
    )
    lines.append(
        f"  declared: {', '.join(explanation_dict['capabilities_declared']) or '—'}"
    )
    if explanation_dict["capabilities_missing"]:
        lines.append(
            f"  ⚠️  MISSING (required but not declared): "
            f"{', '.join(explanation_dict['capabilities_missing'])}"
        )

    if explanation_dict["feature_flags"]:
        lines.append("")
        lines.append("Feature flags:")
        for k, v in explanation_dict["feature_flags"].items():
            lines.append(f"  {k} = {v}")

    if explanation_dict["issues"]:
        lines.append("")
        lines.append("Issues:")
        for issue in explanation_dict["issues"]:
            lines.append(f"  ⚠️  {issue}")

    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    """CLI entry point для ``gd route explain`` команды.

    Args:
        argv: Опциональный список аргументов (для тестирования).

    Returns:
        Exit code: 0 если explanation completed (даже с issues),
        1 если --strict и есть issues, 2 если ошибка parse.
    """
    parser = argparse.ArgumentParser(
        description=(
            "Explain route structure: graph, side effects, capabilities, "
            "retry/time budgets, feature flags."
        )
    )
    parser.add_argument(
        "route_dir",
        type=Path,
        help="Каталог route (содержит route.toml + *.dsl.yaml).",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Machine-readable JSON output.",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Exit 1 если есть issues (capabilities missing, timeout overflow).",
    )
    args = parser.parse_args(argv)

    try:
        explanation = explain_route(args.route_dir)
    except (ValueError, FileNotFoundError) as exc:
        sys.stderr.write(f"❌ {exc}\n")
        return 2

    out = explanation.to_dict()
    if args.json:
        sys.stdout.write(json.dumps(out, ensure_ascii=False, indent=2) + "\n")
    else:
        sys.stdout.write(_print_human(out))

    if args.strict and out["issues"]:
        sys.stderr.write(
            f"\nFAILED: {len(out['issues'])} issue(s). Use --json для details.\n"
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
