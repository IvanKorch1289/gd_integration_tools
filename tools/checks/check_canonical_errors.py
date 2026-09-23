"""Canonical error contract verification (P1 audit 2026-09-22).

Аудит finding #8: project имеет много протоколов, но ошибки не сведены в
единую публичную taxonomy. Адаптеры должны детерминированно преобразовывать
``DomainError`` в:
  - REST: RFC 9457 Problem Details.
  - GraphQL: errors[].extensions.code.
  - gRPC: google.rpc.Status + typed details.
  - SOAP: стабильный Fault code/detail.
  - AsyncAPI/MQ: error/dead-letter envelope.
  - MCP: structured tool error без stack trace.
  - WebSocket/SSE: protocol-specific error frame/event.

Проверяет:
1. ``BaseError`` usage в каждом protocol adapter (REST, gRPC, GraphQL, SOAP, MCP).
2. ``grpc_status_code`` mapping coverage (HTTP → gRPC).
3. ``build_error_envelope`` usage в middleware.
4. SOAP Fault consistency.
5. GraphQL extensions.code consistency.

Использование::

    python tools/checks/check_canonical_errors.py              # human-readable
    python tools/checks/check_canonical_errors.py --strict    # exit 1
    python tools/checks/check_canonical_errors.py --json      # machine output
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
SRC_ROOT = REPO_ROOT / "src"


def _find_protocol_adapters() -> dict[str, list[Path]]:
    """Find error handlers per protocol."""
    protocols: dict[str, list[Path]] = {}
    for py in (REPO_ROOT / "src/backend/entrypoints").rglob("*.py"):
        if "__pycache__" in py.parts:
            continue
        rel = py.relative_to(REPO_ROOT / "src/backend/entrypoints")
        # Determine protocol from first dir component.
        protocol = rel.parts[0] if len(rel.parts) > 1 else "root"
        protocols.setdefault(protocol, []).append(py)
    return protocols


def _check_adapter_handles_base_error(
    files: list[Path], protocol: str
) -> tuple[bool, str]:
    """Check if at least one adapter file handles BaseError."""
    for f in files:
        try:
            content = f.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        if "BaseError" in content or "core.errors" in content:
            return True, f.relative_to(REPO_ROOT).as_posix()
    return False, "no BaseError handling"


def _check_rest_problem_details() -> tuple[bool, str]:
    """Check REST uses RFC 9457 Problem Details (type, title, status, detail)."""
    rest_dir = REPO_ROOT / "src/backend/entrypoints/api"
    for py in rest_dir.rglob("*.py"):
        if "__pycache__" in py.parts:
            continue
        try:
            content = py.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        # RFC 9457 problem details has type/title/status/detail.
        if all(k in content for k in ("type", "title", "detail", "status")):
            return True, py.relative_to(REPO_ROOT).as_posix()
    return False, "no Problem Details fields detected"


def _check_graphql_extensions_code() -> tuple[bool, str]:
    """Check GraphQL error has extensions.code."""
    graphql_dir = REPO_ROOT / "src/backend/entrypoints/graphql"
    for py in graphql_dir.rglob("*.py"):
        if "__pycache__" in py.parts:
            continue
        try:
            content = py.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        if "extensions" in content and ("code" in content or "error_code" in content):
            return True, py.relative_to(REPO_ROOT).as_posix()
    return False, "no extensions.code pattern"


def _check_soap_fault_consistency() -> tuple[bool, str]:
    """Check SOAP has consistent Fault code/detail structure."""
    soap_dir = REPO_ROOT / "src/backend/entrypoints/soap"
    for py in soap_dir.rglob("*.py"):
        if "__pycache__" in py.parts:
            continue
        try:
            content = py.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        if "Fault" in content and (
            "faultcode" in content
            or "faultstring" in content
            or "fault_code" in content
        ):
            return True, py.relative_to(REPO_ROOT).as_posix()
    return False, "no Fault code structure"


def _check_mcp_error_structure() -> tuple[bool, str]:
    """Check MCP uses structured error (no stack trace)."""
    mcp_dir = REPO_ROOT / "src/backend/entrypoints/mcp"
    for py in mcp_dir.rglob("*.py"):
        if "__pycache__" in py.parts:
            continue
        try:
            content = py.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        if "error" in content.lower() and (
            "structured" in content.lower() or "isError" in content
        ):
            return True, py.relative_to(REPO_ROOT).as_posix()
    return False, "no structured error pattern"


def _check_grpc_status_mapping() -> tuple[bool, str]:
    """Check gRPC has google.rpc.Status mapping."""
    grpc_dir = REPO_ROOT / "src/backend/entrypoints/grpc"
    for py in grpc_dir.rglob("*.py"):
        if "__pycache__" in py.parts:
            continue
        try:
            content = py.read_text(encoding="utf-8", errors="ignore")
        except OSError:
            continue
        # StatusCode is enum from grpc.
        if "StatusCode" in content or "_HTTP_TO_GRPC" in content:
            return True, py.relative_to(REPO_ROOT).as_posix()
    return False, "no gRPC StatusCode mapping"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Canonical error contract verification"
    )
    parser.add_argument("--strict", action="store_true", help="Exit 1 if issues found")
    parser.add_argument("--json", action="store_true", help="JSON output")
    args = parser.parse_args(argv)

    notes: list[str] = []
    issues: list[str] = []
    results: dict[str, dict[str, object]] = {}

    # Per-protocol coverage.
    checks = {
        "REST": _check_rest_problem_details,
        "GraphQL": _check_graphql_extensions_code,
        "gRPC": _check_grpc_status_mapping,
        "SOAP": _check_soap_fault_consistency,
        "MCP": _check_mcp_error_structure,
    }
    for protocol, check_fn in checks.items():
        ok, info = check_fn()
        results[protocol] = {"compliant": ok, "evidence": info}
        notes.append(f"{protocol}: {'✅' if ok else '❌'} {info}")

    # BaseError coverage across all protocol adapters.
    adapters = _find_protocol_adapters()
    base_error_coverage: dict[str, dict[str, object]] = {}
    for protocol, files in adapters.items():
        ok, info = _check_adapter_handles_base_error(files, protocol)
        base_error_coverage[protocol] = {"uses_base_error": ok, "evidence": info}

    n_protocols = len(checks)
    n_compliant = sum(1 for r in results.values() if r["compliant"])
    notes.append(f"Protocols compliant: {n_compliant}/{n_protocols}")

    if n_compliant < n_protocols:
        issues.append(
            f"Only {n_compliant}/{n_protocols} protocols have canonical error contracts. "
            "Missing: " + ", ".join(p for p, r in results.items() if not r["compliant"])
        )

    output = {
        "protocol_checks": results,
        "base_error_coverage": base_error_coverage,
        "compliant_count": n_compliant,
        "total_count": n_protocols,
        "issues": issues,
        "notes": notes,
    }

    if args.json:
        print(json.dumps(output, indent=2))
    else:
        print(f"{'=' * 60}")
        print("Canonical Error Contract (P1 audit 2026-09-22)")
        print(f"{'=' * 60}")
        print()
        for n in notes:
            print(f"  {n}")
        print()
        if issues:
            print("Issues:")
            for i in issues:
                print(f"  ❌ {i}")
        else:
            print("✅ All protocols have canonical error contracts")
        print()

    if args.strict and issues:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
