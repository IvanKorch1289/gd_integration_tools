"""CLI: gd connector certify <plugin> (25.09 audit #10).

Per 25.09 audit: «gd connector certify <plugin> с timeout/429/5xx/
schema-drift/replay tests».

Usage::

    python -m src.backend.core.connector.cli certify <plugin_name>
    python -m src.backend.core.connector.cli certify <plugin_name> --json

Output: human-readable summary + per-test results, или JSON.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys

from src.backend.core.connector.certify import certify_connector
from src.backend.core.connector.manifest import (
    AuthConfig,
    ConnectorAuthType,
    ConnectorManifest,
)


def _human_report(report_dict: dict) -> str:
    """Human-readable certification report."""
    lines = [
        f"Connector: {report_dict['connector_name']}",
        f"Endpoint: {report_dict['endpoint']}",
        f"Data classification: {report_dict['data_classification']}",
        f"Timestamp: {report_dict['timestamp']}",
        "",
        f"Tests ({len(report_dict['tests'])}):",
    ]
    for t in report_dict["tests"]:
        status = "✅" if t["passed"] else "❌"
        lines.append(f"  {status} {t['test_name']:<20} {t['duration_ms']:.1f}ms")
        if t["error"]:
            lines.append(f"        error: {t['error']}")
        for k, v in t["details"].items():
            lines.append(f"        {k}: {v}")

    lines.append("")
    verdict = "✅ PASSED" if report_dict["overall_passed"] else "❌ FAILED"
    lines.append(f"Overall verdict: {verdict}")
    return "\n".join(lines) + "\n"


def _build_demo_manifest(plugin_name: str) -> ConnectorManifest:
    """Build demo :class:`ConnectorManifest` for plugin (MVP — real parsing TBD).

    Для Sprint 7 follow-up: parse ``extensions/<plugin>/plugin.toml`` +
    connector-specific fields из ``connector.toml`` (когда schema определена).
    """
    from src.backend.core.plugin_runtime.manifest_toml import PluginManifest

    base = PluginManifest(
        name=plugin_name,
        version="0.1.0",
        requires_core=">=0.20,<0.21",
        entry_class=f"extensions.{plugin_name}.entry:Entry",
    )
    return ConnectorManifest.from_plugin_manifest(
        base=base,
        endpoint=f"https://api.{plugin_name}.example.com/v1",
        auth=AuthConfig(
            type=ConnectorAuthType.API_KEY, secret_ref=f"vault://{plugin_name}/api_key"
        ),
        operations=(f"{plugin_name}.list", f"{plugin_name}.get"),
    )


def main(argv: list[str] | None = None) -> int:
    """CLI entry point для ``gd connector certify`` команды.

    Args:
        argv: Опциональный список аргументов (для тестирования).

    Returns:
        Exit code: 0 если certification passed, 1 если failed, 2 если error.
    """
    parser = argparse.ArgumentParser(
        description=(
            "Connector certification runner: timeout/429/5xx/schema-drift/replay."
        )
    )
    sub = parser.add_subparsers(dest="command", required=True)

    cert = sub.add_parser("certify", help="Run certification matrix на connector'е")
    cert.add_argument(
        "plugin_name", type=str, help="Имя plugin'а (например 'dadata', 'skb')."
    )
    cert.add_argument(
        "--json", action="store_true", help="Machine-readable JSON output."
    )
    cert.add_argument(
        "--strict", action="store_true", help="Exit 1 если overall_passed=False."
    )

    args = parser.parse_args(argv)

    if args.command != "certify":
        sys.stderr.write(f"❌ unknown command: {args.command}\n")
        return 2

    try:
        manifest = _build_demo_manifest(args.plugin_name)
        report = asyncio.run(certify_connector(manifest))
    except Exception as exc:
        sys.stderr.write(f"❌ {exc}\n")
        return 2

    out = report.to_dict()
    if args.json:
        sys.stdout.write(json.dumps(out, ensure_ascii=False, indent=2) + "\n")
    else:
        sys.stdout.write(_human_report(out))

    if args.strict and not out["overall_passed"]:
        sys.stderr.write(
            "\nFAILED: certification matrix has failures. Use --json для details.\n"
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
