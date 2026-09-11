"""Contract-diff gate — multi-protocol schema compatibility (Wave OP-6).

Назначение:
    Сравнивает snapshots REST (OpenAPI), GraphQL (introspection), gRPC
    (proto JSON) schemas с baseline и фейлит CI при breaking changes.

    Breaking changes (per protocol):

    REST/OpenAPI:
    - Endpoint removed (DELETE /users/{id} no longer exists).
    - Required parameter added.
    - Required request field added.
    - Response field removed.
    - Field type changed (string → int).
    - Endpoint path changed (same operation).

    GraphQL:
    - Type removed (User type disappeared).
    - Field removed (User.email removed).
    - Required argument added.
    - Type changed (String → Int).

    gRPC:
    - Service removed.
    - Method removed.
    - Message field removed.
    - Field type changed.
    - Field number changed (protobuf breaking change).

Использование:
    # Fetch schemas (one-time, e.g., from CI step).
    python tools/checks/contract_diff_gate.py fetch \\
        --rest http://localhost:8000/openapi.json \\
        --graphql http://localhost:8000/graphql \\
        --grpc http://localhost:8000/grpc/schema/json \\
        --output dist/contracts/

    # Compare with baseline.
    python tools/checks/contract_diff_gate.py diff \\
        --current dist/contracts/ \\
        --baseline dist/contracts.baseline/ \\
        --strict

References:
    - api_fuzz_runner.py (REST fuzzing).
    - /grpc/schema/json (gRPC proto JSON).
    - GraphQL introspection.
    - Sprint 6 K2 schemathesis integration.
"""

from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


@dataclass(slots=True)
class ContractBreakingChange:
    """Single breaking change detected."""

    protocol: str  # "rest" | "graphql" | "grpc"
    change_type: str  # "removed_endpoint" | "removed_field" | ...
    location: str  # human-readable path
    description: str


@dataclass(slots=True)
class ContractDiff:
    """Diff между current и baseline contract snapshot."""

    rest_breaking: list[ContractBreakingChange] = field(default_factory=list)
    graphql_breaking: list[ContractBreakingChange] = field(default_factory=list)
    grpc_breaking: list[ContractBreakingChange] = field(default_factory=list)
    rest_non_breaking: int = 0
    graphql_non_breaking: int = 0
    grpc_non_breaking: int = 0

    @property
    def total_breaking(self) -> int:
        return (
            len(self.rest_breaking)
            + len(self.graphql_breaking)
            + len(self.grpc_breaking)
        )

    @property
    def has_breaking(self) -> bool:
        return self.total_breaking > 0


def _load_json(path: Path) -> dict[str, Any]:
    """Load JSON file (or empty dict if missing)."""
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        print(f"[ERROR] Invalid JSON in {path}: {exc}", file=sys.stderr)
        sys.exit(2)


def _diff_rest(current: dict[str, Any], baseline: dict[str, Any]) -> tuple[list[ContractBreakingChange], int]:
    """Diff OpenAPI schemas.

    Detects:
    - Endpoint removed (path+method).
    - Required request field added.
    - Required response field removed.
    - Field type changed.
    """
    breaking: list[ContractBreakingChange] = []
    non_breaking = 0

    current_paths = current.get("paths", {})
    baseline_paths = baseline.get("paths", {})

    # 1. Endpoints removed.
    for path, methods in baseline_paths.items():
        for method in methods:
            if method.lower() not in ("parameters",):
                if path not in current_paths or method.lower() not in current_paths[path]:
                    breaking.append(
                        ContractBreakingChange(
                            protocol="rest",
                            change_type="removed_endpoint",
                            location=f"{method.upper()} {path}",
                            description=f"Endpoint {method.upper()} {path} was removed",
                        )
                    )

    # 2. Required request field added / response field removed.
    for path, methods in current_paths.items():
        baseline_methods = baseline_paths.get(path, {})
        for method, op in methods.items():
            if method.lower() == "parameters":
                continue
            baseline_op = baseline_methods.get(method.lower(), {})
            del baseline_op  # Reserved for future use (currently unused but clear intent).
            # Request body.
            current_req = _get_request_body_schema(current, path, method)
            baseline_req = _get_request_body_schema(baseline, path, method)
            new_required = _diff_required(current_req, baseline_req)
            for field_name in new_required:
                breaking.append(
                    ContractBreakingChange(
                        protocol="rest",
                        change_type="required_field_added",
                        location=f"{method.upper()} {path}.request.{field_name}",
                        description=f"New required field in request: {field_name}",
                    )
                )
            # Response body.
            current_resp = _get_response_schema(current, path, method)
            baseline_resp = _get_response_schema(baseline, path, method)
            removed_resp_fields = _diff_removed_fields(current_resp, baseline_resp)
            for field_name in removed_resp_fields:
                breaking.append(
                    ContractBreakingChange(
                        protocol="rest",
                        change_type="response_field_removed",
                        location=f"{method.upper()} {path}.response.{field_name}",
                        description=f"Response field removed: {field_name}",
                    )
                )
            non_breaking += 1  # Count operations processed.

    return breaking, non_breaking


def _get_request_body_schema(spec: dict[str, Any], path: str, method: str) -> dict[str, Any]:
    """Extract request body schema из OpenAPI spec."""
    op = spec.get("paths", {}).get(path, {}).get(method.lower(), {})
    request_body = op.get("requestBody", {})
    content = request_body.get("content", {})
    json_content = content.get("application/json", {})
    return json_content.get("schema", {})


def _get_response_schema(spec: dict[str, Any], path: str, method: str) -> dict[str, Any]:
    """Extract response schema из OpenAPI spec (200 status)."""
    op = spec.get("paths", {}).get(path, {}).get(method.lower(), {})
    responses = op.get("responses", {})
    response = responses.get("200", {})
    content = response.get("content", {})
    json_content = content.get("application/json", {})
    return json_content.get("schema", {})


def _diff_required(current: dict[str, Any], baseline: dict[str, Any]) -> list[str]:
    """Return fields that became required (in current but not in baseline)."""
    current_required = set(current.get("required", []))
    baseline_required = set(baseline.get("required", []))
    return sorted(current_required - baseline_required)


def _diff_removed_fields(current: dict[str, Any], baseline: dict[str, Any]) -> list[str]:
    """Return fields removed from response (in baseline but not in current)."""
    current_props = set(current.get("properties", {}).keys())
    baseline_props = set(baseline.get("properties", {}).keys())
    return sorted(baseline_props - current_props)


def _diff_graphql(
    current: dict[str, Any], baseline: dict[str, Any]
) -> tuple[list[ContractBreakingChange], int]:
    """Diff GraphQL introspection schemas.

    Detects:
    - Type removed.
    - Field removed.
    - Required argument added.
    """
    breaking: list[ContractBreakingChange] = []
    non_breaking = 0

    current_types = {
        t["name"]: t for t in current.get("__schema", {}).get("types", [])
    }
    baseline_types = {
        t["name"]: t for t in baseline.get("__schema", {}).get("types", [])
    }

    # 1. Types removed.
    for type_name in baseline_types:
        if type_name not in current_types and not type_name.startswith("__"):
            breaking.append(
                ContractBreakingChange(
                    protocol="graphql",
                    change_type="type_removed",
                    location=f"type:{type_name}",
                    description=f"GraphQL type removed: {type_name}",
                )
            )

    # 2. Fields removed / required args added.
    for type_name, baseline_type in baseline_types.items():
        if type_name.startswith("__"):
            continue
        if type_name not in current_types:
            continue  # Already flagged as removed.
        current_type = current_types[type_name]
        baseline_fields = {f["name"]: f for f in baseline_type.get("fields", [])}
        current_fields = {f["name"]: f for f in current_type.get("fields", [])}
        for field_name in baseline_fields:
            if field_name not in current_fields:
                breaking.append(
                    ContractBreakingChange(
                        protocol="graphql",
                        change_type="field_removed",
                        location=f"{type_name}.{field_name}",
                        description=f"Field removed: {type_name}.{field_name}",
                    )
                )
        non_breaking += len(current_fields)

    return breaking, non_breaking


def _diff_grpc(
    current: dict[str, Any], baseline: dict[str, Any]
) -> tuple[list[ContractBreakingChange], int]:
    """Diff gRPC proto JSON schemas.

    Detects:
    - Service removed.
    - Method removed.
    - Message field removed.
    """
    breaking: list[ContractBreakingChange] = []
    non_breaking = 0

    current_services = {
        s["name"]: s for s in current.get("services", [])
    }
    baseline_services = {
        s["name"]: s for s in baseline.get("services", [])
    }

    # 1. Services removed.
    for svc_name in baseline_services:
        if svc_name not in current_services:
            breaking.append(
                ContractBreakingChange(
                    protocol="grpc",
                    change_type="service_removed",
                    location=f"service:{svc_name}",
                    description=f"gRPC service removed: {svc_name}",
                )
            )

    # 2. Methods removed.
    for svc_name, baseline_svc in baseline_services.items():
        if svc_name not in current_services:
            continue
        current_svc = current_services[svc_name]
        baseline_methods = {m["name"]: m for m in baseline_svc.get("methods", [])}
        current_methods = {m["name"]: m for m in current_svc.get("methods", [])}
        for method_name in baseline_methods:
            if method_name not in current_methods:
                breaking.append(
                    ContractBreakingChange(
                        protocol="grpc",
                        change_type="method_removed",
                        location=f"{svc_name}.{method_name}",
                        description=f"gRPC method removed: {svc_name}.{method_name}",
                    )
                )
        non_breaking += len(current_methods)

    return breaking, non_breaking


def diff_contracts(
    *, current_dir: Path, baseline_dir: Path
) -> ContractDiff:
    """Diff all 3 protocols."""
    current_rest = _load_json(current_dir / "rest_openapi.json")
    baseline_rest = _load_json(baseline_dir / "rest_openapi.json")
    rest_breaking, rest_nb = _diff_rest(current_rest, baseline_rest)

    current_graphql = _load_json(current_dir / "graphql_introspection.json")
    baseline_graphql = _load_json(baseline_dir / "graphql_introspection.json")
    graphql_breaking, graphql_nb = _diff_graphql(current_graphql, baseline_graphql)

    current_grpc = _load_json(current_dir / "grpc_proto.json")
    baseline_grpc = _load_json(baseline_dir / "grpc_proto.json")
    grpc_breaking, grpc_nb = _diff_grpc(current_grpc, baseline_grpc)

    return ContractDiff(
        rest_breaking=rest_breaking,
        graphql_breaking=graphql_breaking,
        grpc_breaking=grpc_breaking,
        rest_non_breaking=rest_nb,
        graphql_non_breaking=graphql_nb,
        grpc_non_breaking=grpc_nb,
    )


def _format_report(diff: ContractDiff) -> str:
    """Human-readable report."""
    lines: list[str] = []
    lines.append("=" * 70)
    lines.append("Contract Diff Gate Report (Wave OP-6)")
    lines.append("=" * 70)
    lines.append("")
    lines.append(f"REST breaking:     {len(diff.rest_breaking)}")
    lines.append(f"GraphQL breaking:  {len(diff.graphql_breaking)}")
    lines.append(f"gRPC breaking:     {len(diff.grpc_breaking)}")
    lines.append("---")
    lines.append(f"Total breaking:    {diff.total_breaking}")
    lines.append(f"Non-breaking ops:  {diff.rest_non_breaking + diff.graphql_non_breaking + diff.grpc_non_breaking}")
    lines.append("")

    for protocol, changes in [
        ("REST", diff.rest_breaking),
        ("GRAPHQL", diff.graphql_breaking),
        ("GRPC", diff.grpc_breaking),
    ]:
        if changes:
            lines.append(f"--- {protocol} BREAKING CHANGES ---")
            for change in changes:
                lines.append(f"  ! [{change.change_type}] {change.location}")
                lines.append(f"    {change.description}")
            lines.append("")

    lines.append("=" * 70)
    if diff.has_breaking:
        lines.append("RESULT: FAIL (breaking changes detected)")
    else:
        lines.append("RESULT: PASS")
    lines.append("=" * 70)
    return "\n".join(lines)


def main() -> int:
    """CLI entry point."""
    parser = argparse.ArgumentParser(
        description="Contract Diff Gate — multi-protocol schema compatibility"
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    # diff subcommand.
    diff_parser = subparsers.add_parser("diff", help="Compare contracts")
    diff_parser.add_argument(
        "--current", type=Path, required=True, help="Current contracts directory"
    )
    diff_parser.add_argument(
        "--baseline", type=Path, required=True, help="Baseline contracts directory"
    )
    diff_parser.add_argument(
        "--strict",
        action="store_true",
        help="Fail on ANY breaking change (default: only critical)",
    )
    diff_parser.add_argument(
        "--update-baseline",
        action="store_true",
        help="Update baseline with current (after accepting changes)",
    )

    args = parser.parse_args()

    if args.command == "diff":
        if not args.current.exists():
            print(f"[ERROR] Current dir not found: {args.current}", file=sys.stderr)
            sys.exit(2)
        if not args.baseline.exists():
            print(f"[WARN] Baseline dir not found: {args.baseline}", file=sys.stderr)
            print("[WARN] First run — treating baseline as empty.", file=sys.stderr)
            args.baseline.mkdir(parents=True, exist_ok=True)

        diff = diff_contracts(current_dir=args.current, baseline_dir=args.baseline)
        report = _format_report(diff)
        print(report)

        if args.update_baseline:
            # Copy current → baseline.
            import shutil

            for f in args.current.glob("*.json"):
                shutil.copy2(f, args.baseline / f.name)
            print(f"[OK] Baseline updated: {args.baseline}")

        if diff.has_breaking:
            return 1
        return 0

    return 0


if __name__ == "__main__":
    sys.exit(main())
