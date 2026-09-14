"""API Importer — OpenAPI/Swagger parser + draft generator (Wave 2 DX).

Pure-Python, no external deps (no prance/openapi-spec-validator).
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

__all__ = (
    "APIImporter",
    "ConnectorDraft",
    "ImportedAPI",
    "OperationInfo",
    "PathInfo",
    "export_route_draft",
    "generate_connector_draft",
    "generate_route_draft",
    "import_openapi",
    "import_swagger",
)


# OpenAPI 3.0 supported methods.
_OPENAPI_METHODS = ("get", "post", "put", "patch", "delete", "options", "head", "trace")
# Swagger 2.0 supported methods (same).
_SWAGGER_METHODS = _OPENAPI_METHODS


@dataclass(slots=True)
class OperationInfo:
    """Single operation (endpoint method)."""

    method: str  # GET, POST, etc.
    path: str
    operation_id: str = ""
    summary: str = ""
    description: str = ""
    tags: list[str] = field(default_factory=list)
    parameters: list[dict[str, Any]] = field(default_factory=list)
    request_body: dict[str, Any] = field(default_factory=dict)
    responses: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class PathInfo:
    """Path с одним или more operations."""

    path: str
    summary: str = ""
    description: str = ""
    operations: list[OperationInfo] = field(default_factory=list)


@dataclass(slots=True)
class ImportedAPI:
    """Parsed API spec."""

    title: str = ""
    version: str = ""
    description: str = ""
    servers: list[dict[str, Any]] = field(default_factory=list)
    paths: list[PathInfo] = field(default_factory=list)
    components: dict[str, Any] = field(default_factory=dict)
    source_format: str = ""  # "openapi3" | "swagger2"

    def operation_count(self) -> int:
        return sum(len(p.operations) for p in self.paths)


@dataclass(slots=True)
class ConnectorDraft:
    """Generated connector draft from ImportedAPI."""

    name: str
    version: str
    base_url: str
    auth_schemes: list[str] = field(default_factory=list)
    operations: list[dict[str, Any]] = field(default_factory=list)
    schemas: dict[str, Any] = field(default_factory=dict)


def import_openapi(spec: dict[str, Any]) -> ImportedAPI:
    """Parse OpenAPI 3.x specification."""
    info = spec.get("info", {})
    api = ImportedAPI(
        title=info.get("title", ""),
        version=info.get("version", ""),
        description=info.get("description", ""),
        servers=list(spec.get("servers", [])),
        components=dict(spec.get("components", {})),
        source_format="openapi3",
    )
    paths = spec.get("paths", {})
    for path, path_item in paths.items():
        summary = path_item.get("summary", "")
        description = path_item.get("description", "")
        path_info = PathInfo(
            path=path,
            summary=summary,
            description=description,
        )
        for method in _OPENAPI_METHODS:
            op = path_item.get(method)
            if not isinstance(op, dict):
                continue
            path_info.operations.append(
                OperationInfo(
                    method=method.upper(),
                    path=path,
                    operation_id=op.get("operationId", ""),
                    summary=op.get("summary", ""),
                    description=op.get("description", ""),
                    tags=list(op.get("tags", [])),
                    parameters=list(op.get("parameters", [])),
                    request_body=dict(op.get("requestBody", {})),
                    responses=dict(op.get("responses", {})),
                )
            )
        if path_info.operations:
            api.paths.append(path_info)
    logger.info(
        "import_openapi: %d paths, %d operations",
        len(api.paths),
        api.operation_count(),
    )
    return api


def import_swagger(spec: dict[str, Any]) -> ImportedAPI:
    """Parse Swagger 2.0 specification."""
    info = spec.get("info", {})
    api = ImportedAPI(
        title=info.get("title", ""),
        version=info.get("version", ""),
        description=info.get("description", ""),
        components=dict(spec.get("definitions", {})),
        source_format="swagger2",
    )
    # Swagger 2.0: host + basePath + schemes → base URL.
    host = spec.get("host", "")
    base_path = spec.get("basePath", "")
    schemes = spec.get("schemes", ["https"])
    if host:
        scheme = schemes[0] if schemes else "https"
        api.servers.append({"url": f"{scheme}://{host}{base_path}"})

    paths = spec.get("paths", {})
    for path, path_item in paths.items():
        summary = path_item.get("summary", "")
        description = path_item.get("description", "")
        path_info = PathInfo(
            path=path,
            summary=summary,
            description=description,
        )
        for method in _SWAGGER_METHODS:
            op = path_item.get(method)
            if not isinstance(op, dict):
                continue
            # Swagger 2.0 body is in parameters with in=body.
            body_param = next(
                (p for p in op.get("parameters", []) if p.get("in") == "body"),
                {},
            )
            other_params = [
                p for p in op.get("parameters", []) if p.get("in") != "body"
            ]
            path_info.operations.append(
                OperationInfo(
                    method=method.upper(),
                    path=path,
                    operation_id=op.get("operationId", ""),
                    summary=op.get("summary", ""),
                    description=op.get("description", ""),
                    tags=list(op.get("tags", [])),
                    parameters=other_params,
                    request_body=body_param,
                    responses=dict(op.get("responses", {})),
                )
            )
        if path_info.operations:
            api.paths.append(path_info)
    logger.info(
        "import_swagger: %d paths, %d operations",
        len(api.paths),
        api.operation_count(),
    )
    return api


def generate_connector_draft(
    imported: ImportedAPI, name: str | None = None
) -> ConnectorDraft:
    """Generate ConnectorDraft from ImportedAPI."""
    base_url = ""
    if imported.servers:
        base_url = imported.servers[0].get("url", "")
    # Detect auth schemes from securityDefinitions / security.
    auth_schemes: list[str] = []
    components = imported.components or {}
    sec_defs = components.get("securitySchemes", {})
    if not sec_defs:
        # Swagger 2.0: securityDefinitions at top level.
        sec_defs = components.get("securityDefinitions", {}) or components
    for scheme_name, scheme_def in (
        sec_defs.items() if isinstance(sec_defs, dict) else []
    ):
        if isinstance(scheme_def, dict):
            scheme_type = scheme_def.get("type", "unknown")
            auth_schemes.append(f"{scheme_name}({scheme_type})")

    # Build operations list (one per HTTP method+path).
    operations: list[dict[str, Any]] = []
    for path_info in imported.paths:
        for op in path_info.operations:
            operations.append(
                {
                    "name": op.operation_id or f"{op.method.lower()}_{op.path}",
                    "method": op.method,
                    "path": op.path,
                    "summary": op.summary,
                    "description": op.description,
                    "tags": op.tags,
                    "parameters": op.parameters,
                    "request_body": op.request_body,
                }
            )

    return ConnectorDraft(
        name=name or imported.title or "imported_api",
        version=imported.version,
        base_url=base_url,
        auth_schemes=auth_schemes,
        operations=operations,
        schemas=imported.components or {},
    )


def generate_route_draft(
    imported: ImportedAPI, route_id: str
) -> dict[str, str]:
    """Generate route.yaml + test scaffold (as dict of file path → content)."""
    connector = generate_connector_draft(imported, name=route_id)
    files: dict[str, str] = {}

    # route.toml.
    files["route.toml"] = _render_route_toml(connector, route_id)

    # tests scaffold.
    files[f"test_{route_id}.py"] = _render_test_scaffold(connector, route_id)

    return files


def _render_route_toml(connector: ConnectorDraft, route_id: str) -> str:
    """Render route.toml из connector draft."""
    lines: list[str] = []
    lines.append("[route]")
    lines.append(f"id = \"{route_id}\"")
    lines.append(f"source = \"timer:60s|api={connector.base_url}\"")
    lines.append(f"description = \"Auto-generated from {connector.name} {connector.version}\"")
    lines.append(f"owner = \"team-imports\"")
    lines.append("")
    lines.append("[contract]")
    lines.append("timeout_seconds = 30")
    lines.append("idempotency_key_field = \"request_id\"")
    lines.append("dlq_topic = \"events.{route_id}.dlq\"")
    lines.append("")
    lines.append("[security]")
    if connector.auth_schemes:
        lines.append(f"# Auth schemes: {', '.join(connector.auth_schemes)}")
    lines.append("# requires_permission = \"api.read.{}".format(route_id) + "\"")
    return "\n".join(lines) + "\n"


def _render_test_scaffold(connector: ConnectorDraft, route_id: str) -> str:
    """Render contract test scaffold."""
    return f'''"""Contract tests для {route_id} (auto-generated).

Source: {connector.name} v{connector.version}
Generated: API importer
"""

from __future__ import annotations

import pytest

from src.backend.core.contract_testing import (
    ContractTestCase,
    ContractTestHarness,
)


@pytest.fixture
def harness() -> ContractTestHarness:
    return ContractTestHarness()


# TODO: добавить contract tests для каждой operation из {len(connector.operations)}.
# Пример:
# def test_health_check(harness: ContractTestHarness) -> None:
#     spec = ContractTestCase(
#         name="health_check",
#         input_payload={{}},
#         expected_output_schema={{"type": "object"}},
#     )
#     # result = harness.run(spec, my_route_handler)
#     # assert result.passed
'''


def export_route_draft(
    files: dict[str, str], target_dir: str | Path
) -> list[Path]:
    """Write generated files в target directory.

    Returns:
        List of written file paths.
    """
    target = Path(target_dir)
    target.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for rel_path, content in files.items():
        full_path = target / rel_path
        full_path.parent.mkdir(parents=True, exist_ok=True)
        full_path.write_text(content, encoding="utf-8")
        written.append(full_path)
        logger.info("Wrote %s (%d bytes)", full_path, len(content))
    return written


class APIImporter:
    """High-level facade."""

    def __init__(self) -> None:
        pass

    def import_from_file(self, path: str | Path) -> ImportedAPI:
        """Import API from JSON file (auto-detect OpenAPI 3.x or Swagger 2.0)."""
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        if "openapi" in data:
            return import_openapi(data)
        if "swagger" in data:
            return import_swagger(data)
        raise ValueError(f"Unknown spec format in {path}")

    def import_from_dict(
        self, spec: dict[str, Any]
    ) -> ImportedAPI:
        """Import API from dict (auto-detect)."""
        if "openapi" in spec:
            return import_openapi(spec)
        if "swagger" in spec:
            return import_swagger(spec)
        raise ValueError("Unknown spec format (no 'openapi' or 'swagger' key)")
