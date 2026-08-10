"""CLI generate command — генерация DSL кода, маршрутов и шаблонов.

Wave [wave:h1-cli-generate]
K-ARCH-2: CLI tooling for developer experience.

Phase 3 fix: migrated from click to typer (click→typer migration).
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import typer
import yaml

# Add parent to path for imports
CLI_DIR = Path(__file__).parent
DSL_DIR = CLI_DIR.parent
BACKEND_DIR = DSL_DIR.parent
SRC_DIR = BACKEND_DIR.parent
sys.path.insert(0, str(SRC_DIR))

from src.backend.dsl.blueprint_loader import discover_blueprints

app = typer.Typer(help="DSL Code Generation CLI.")


@app.command("route")
def generate_route(
    route_name: str = typer.Argument(..., help="Name of the route to generate (e.g., 'customer-api')."),
    output: str | None = typer.Option(None, "--output", "-o", help="Output file path"),
    template: str = typer.Option("default", "--template", "-t", help="Template name"),
    protocol: str = typer.Option("rest", "--protocol", help="Protocol (rest, soap, grpc, etc.)"),
) -> None:
    """Generate a new DSL route."""
    route_template = _build_route_template(route_name, template, protocol)

    yaml_content = yaml.dump(route_template, default_flow_style=False, sort_keys=False)

    output_path = (
        Path(output) if output else Path(f"routes/{route_name}/{route_name}.dsl.yaml")
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with open(output_path, "w") as f:
        f.write(yaml_content)

    typer.echo(f"Generated route: {output_path}")
    typer.echo(f"  Protocol: {protocol}")
    typer.echo(f"  Template: {template}")


@app.command("service")
def generate_service(
    service_name: str = typer.Argument(...),
    output: str | None = typer.Option(None, "--output", "-o"),
    crud: bool = typer.Option(False, "--crud", help="Generate CRUD operations"),
) -> None:
    """Generate a service DSL definition."""
    service_dsl = _build_service_dsl(service_name, crud)
    toml_content = _to_toml_style(service_dsl)

    output_path = (
        Path(output) if output else Path(f"services/{service_name}.service.toml")
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with open(output_path, "w") as f:
        f.write(toml_content)

    typer.echo(f"Generated service: {output_path}")
    if crud:
        typer.echo("  CRUD operations: enabled")


@app.command("blueprint")
def generate_blueprint(
    blueprint_name: str = typer.Argument(...),
    output: str | None = typer.Option(None, "--output", "-o"),
    type: str = typer.Option("rest-to-db", "--type", "-t", help="Blueprint type"),
) -> None:
    """Generate a blueprint definition."""
    blueprints = discover_blueprints()
    if blueprints:
        blueprint_template = {
            "blueprint": blueprint_name,
            "version": "1.0.0",
            "description": f"Auto-generated blueprint: {blueprint_name}",
            "tags": [type],
            "params": [],
            "from": {"type": "rest"},
            "steps": [{"name": "log", "type": "log", "params": {"message": "Step 1"}}],
            "to": {"type": "log"},
        }
    else:
        blueprint_template = {
            "blueprint": blueprint_name,
            "version": "1.0.0",
            "description": f"Auto-generated blueprint: {blueprint_name}",
            "type": type,
        }

    yaml_content = yaml.dump(
        blueprint_template, default_flow_style=False, sort_keys=False
    )

    output_path = (
        Path(output) if output else Path(f"blueprints/{blueprint_name}.blueprint.yaml")
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with open(output_path, "w") as f:
        f.write(yaml_content)

    typer.echo(f"Generated blueprint: {output_path}")
    typer.echo(f"  Type: {type}")


@app.command("processor")
def generate_processor(
    processor_name: str = typer.Argument(...),
    output: str | None = typer.Option(None, "--output", "-o"),
    type: str = typer.Option("generic", "--type", "-t", help="Processor type"),
    is_async: bool = typer.Option(False, "--async", help="Generate async processor"),
) -> None:
    """Generate a processor Python stub."""
    processor_code = _build_processor_code(processor_name, type, is_async)

    output_path = (
        Path(output) if output else Path(f"processors/{processor_name.lower()}.py")
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with open(output_path, "w") as f:
        f.write(processor_code)

    typer.echo(f"Generated processor: {output_path}")
    typer.echo(f"  Type: {type}")
    typer.echo(f"  Async: {is_async}")


@app.command("workflow")
def generate_workflow(
    workflow_name: str = typer.Argument(...),
    output: str | None = typer.Option(None, "--output", "-o"),
    steps: int = typer.Option(3, "--steps", "-s", help="Number of initial steps"),
) -> None:
    """Generate a workflow DSL definition."""
    workflow_template = _build_workflow_template(workflow_name, steps)

    yaml_content = yaml.dump(
        workflow_template, default_flow_style=False, sort_keys=False
    )

    output_path = (
        Path(output) if output else Path(f"workflows/{workflow_name}.workflow.yaml")
    )
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with open(output_path, "w") as f:
        f.write(yaml_content)

    typer.echo(f"Generated workflow: {output_path}")
    typer.echo(f"  Steps: {steps}")


def _build_route_template(name: str, template: str, protocol: str) -> dict[str, Any]:
    """Build route template based on type."""
    return {
        "route": {
            "id": name,
            "description": f"Auto-generated route: {name}",
            "source": {"type": protocol, "path": f"/api/v1/{name.replace('-', '/')}"},
            "steps": [
                {
                    "name": "log_request",
                    "type": "log",
                    "params": {"message": f"Processing {name}"},
                },
                {
                    "name": "transform",
                    "type": "transform",
                    "params": {"template": "{{body}}"},
                },
            ],
            "sink": {"type": "log"},
        }
    }


def _build_service_dsl(name: str, crud: bool) -> dict[str, Any]:
    """Build service DSL definition."""
    service = {"service": name, "version": "1.0.0", "description": f"Service: {name}"}

    if crud:
        service["endpoints"] = [
            {"method": "GET", "path": f"/{name}", "action": "list"},
            {"method": "POST", "path": f"/{name}", "action": "create"},
            {"method": "GET", "path": f"/{name}/{{id}}", "action": "get"},
            {"method": "PUT", "path": f"/{name}/{{id}}", "action": "update"},
            {"method": "DELETE", "path": f"/{name}/{{id}}", "action": "delete"},
        ]
    else:
        service["endpoints"] = [
            {"method": "GET", "path": f"/{name}", "action": "invoke"}
        ]

    return service


def _to_toml_style(data: dict[str, Any]) -> str:
    """Convert dict to simple TOML-like format."""
    lines = []
    for key, value in data.items():
        if isinstance(value, dict):
            lines.append(f"[{key}]")
            for k, v in value.items():
                lines.append(f"{k} = {v!r}")
        elif isinstance(value, list):
            lines.append(f"{key} = {value!r}")
        else:
            lines.append(f"{key} = {value!r}")
    return "\n".join(lines)


def _build_processor_code(name: str, ptype: str, is_async: bool) -> str:
    """Build processor Python code stub."""
    async_str = "async " if is_async else ""

    return f'''"""Processor: {name}

Generated by DSL CLI.
Type: {ptype}
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from src.backend.core.types.side_effect import SideEffectKind
from src.backend.dsl.engine.processors.base import BaseProcessor

if TYPE_CHECKING:
    from src.backend.dsl.engine.context import ExecutionContext
    from src.backend.dsl.engine.exchange import Exchange


class {name}(BaseProcessor):
    """Processor: {name}.

    Type: {ptype}
    """

    side_effect = SideEffectKind.{_get_side_effect(ptype)}
    compensatable = True

    def __init__(self, name: str | None = None) -> None:
        super().__init__(name=name or "{name}")

    {async_str}def process(
        self, exchange: Exchange[Any], context: ExecutionContext
    ) -> None:
        """Process the exchange.

        Args:
            exchange: The current exchange.
            context: Execution context.
        """
        msg = f"{name!r} ({ptype!r}) not implemented — fill in process() body"
        raise NotImplementedError(msg)
'''


def _get_side_effect(ptype: str) -> str:
    """Get side effect kind based on processor type."""
    mapping = {
        "ai": "SIDE_EFFECTING",
        "rpa": "SIDE_EFFECTING",
        "db": "SIDE_EFFECTING",
        "http": "SIDE_EFFECTING",
        "generic": "PURE",
    }
    return mapping.get(ptype, "PURE")


def _build_workflow_template(name: str, steps: int) -> dict[str, Any]:
    """Build workflow template."""
    workflow_steps = []
    for i in range(steps):
        workflow_steps.append(
            {
                "name": f"step_{i + 1}",
                "processor": "log",
                "params": {"message": f"Step {i + 1} of {name}"},
            }
        )

    return {
        "workflow": {
            "name": name,
            "description": f"Auto-generated workflow: {name}",
            "version": "1.0",
            "steps": workflow_steps,
            "error_handling": {"strategy": "retry", "max_attempts": 3},
        }
    }


if __name__ == "__main__":
    app()
