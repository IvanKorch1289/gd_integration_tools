"""CLI generate command — генерация DSL кода, маршрутов и шаблонов.

Wave [wave:h1-cli-generate]
K-ARCH-2: CLI tooling for developer experience.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path
from typing import Any

import click
import yaml

# Add parent to path for imports
CLI_DIR = Path(__file__).parent
DSL_DIR = CLI_DIR.parent
BACKEND_DIR = DSL_DIR.parent
SRC_DIR = BACKEND_DIR.parent
sys.path.insert(0, str(SRC_DIR))

from src.backend.dsl.blueprint_loader import discover_blueprints


@click.group()
def cli() -> None:
    """DSL Code Generation CLI."""
    pass


@cli.command("route")
@click.argument("route_name")
@click.option("--output", "-o", type=click.Path(), default=None, help="Output file path")
@click.option("--template", "-t", default="default", help="Template name")
@click.option("--protocol", default="rest", help="Protocol (rest, soap, grpc, etc.)")
def generate_route(route_name: str, output: str | None, template: str, protocol: str) -> None:
    """Generate a new DSL route.

    ROUTE_NAME: Name of the route to generate (e.g., 'customer-api').
    """
    route_template = _build_route_template(route_name, template, protocol)

    yaml_content = yaml.dump(route_template, default_flow_style=False, sort_keys=False)

    output_path = Path(output) if output else Path(f"routes/{route_name}/{route_name}.dsl.yaml")
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with open(output_path, "w") as f:
        f.write(yaml_content)

    click.echo(f"Generated route: {output_path}")
    click.echo(f"  Protocol: {protocol}")
    click.echo(f"  Template: {template}")


@cli.command("service")
@click.argument("service_name")
@click.option("--output", "-o", type=click.Path(), default=None, help="Output file path")
@click.option("--crud", is_flag=True, default=False, help="Generate CRUD operations")
def generate_service(service_name: str, output: str | None, crud: bool) -> None:
    """Generate a service DSL definition.

    SERVICE_NAME: Name of the service (e.g., 'customer-service').
    """
    service_dsl = _build_service_dsl(service_name, crud)

    # Convert to TOML-like format for service definitions
    toml_content = _to_toml_style(service_dsl)

    output_path = Path(output) if output else Path(f"services/{service_name}.service.toml")
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with open(output_path, "w") as f:
        f.write(toml_content)

    click.echo(f"Generated service: {output_path}")
    if crud:
        click.echo("  CRUD operations: enabled")


@cli.command("blueprint")
@click.argument("blueprint_name")
@click.option("--output", "-o", type=click.Path(), default=None, help="Output file path")
@click.option("--type", "-t", default="rest-to-db", help="Blueprint type")
def generate_blueprint(blueprint_name: str, output: str | None, type: str) -> None:
    """Generate a blueprint definition.

    BLUEPRINT_NAME: Name of the blueprint.
    """
    blueprints = discover_blueprints()
    # Use first blueprint as template or build a default one
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

    yaml_content = yaml.dump(blueprint_template, default_flow_style=False, sort_keys=False)

    output_path = Path(output) if output else Path(f"blueprints/{blueprint_name}.blueprint.yaml")
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with open(output_path, "w") as f:
        f.write(yaml_content)

    click.echo(f"Generated blueprint: {output_path}")
    click.echo(f"  Type: {type}")


@cli.command("processor")
@click.argument("processor_name")
@click.option("--output", "-o", type=click.Path(), default=None, help="Output file path")
@click.option("--type", "-t", default="generic", help="Processor type (generic, ai, rpa, etc.)")
@click.option("--async", "is_async", is_flag=True, default=False, help="Generate async processor")
def generate_processor(
    processor_name: str, output: str | None, type: str, is_async: bool
) -> None:
    """Generate a processor Python stub.

    PROCESSOR_NAME: Name of the processor (e.g., 'CustomerProcessor').
    """
    processor_code = _build_processor_code(processor_name, type, is_async)

    output_path = Path(output) if output else Path(f"processors/{processor_name.lower()}.py")
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with open(output_path, "w") as f:
        f.write(processor_code)

    click.echo(f"Generated processor: {output_path}")
    click.echo(f"  Type: {type}")
    click.echo(f"  Async: {is_async}")


@cli.command("workflow")
@click.argument("workflow_name")
@click.option("--output", "-o", type=click.Path(), default=None, help="Output file path")
@click.option("--steps", "-s", default=3, help="Number of initial steps")
def generate_workflow(workflow_name: str, output: str | None, steps: int) -> None:
    """Generate a workflow DSL definition.

    WORKFLOW_NAME: Name of the workflow.
    """
    workflow_template = _build_workflow_template(workflow_name, steps)

    yaml_content = yaml.dump(workflow_template, default_flow_style=False, sort_keys=False)

    output_path = Path(output) if output else Path(f"workflows/{workflow_name}.workflow.yaml")
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with open(output_path, "w") as f:
        f.write(yaml_content)

    click.echo(f"Generated workflow: {output_path}")
    click.echo(f"  Steps: {steps}")


def _build_route_template(name: str, template: str, protocol: str) -> dict[str, Any]:
    """Build route template based on type."""
    return {
        "route": {
            "id": name,
            "description": f"Auto-generated route: {name}",
            "source": {
                "type": protocol,
                "path": f"/api/v1/{name.replace('-', '/')}",
            },
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
            "sink": {
                "type": "log",
            },
        }
    }


def _build_service_dsl(name: str, crud: bool) -> dict[str, Any]:
    """Build service DSL definition."""
    service = {
        "service": name,
        "version": "1.0.0",
        "description": f"Service: {name}",
    }

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
            {"method": "GET", "path": f"/{name}", "action": "invoke"},
        ]

    return service


def _to_toml_style(data: dict[str, Any]) -> str:
    """Convert dict to simple TOML-like format."""
    lines = []
    for key, value in data.items():
        if isinstance(value, dict):
            lines.append(f"[{key}]")
            for k, v in value.items():
                lines.append(f"{k} = {repr(v)}")
        elif isinstance(value, list):
            lines.append(f"{key} = {repr(value)}")
        else:
            lines.append(f"{key} = {repr(value)}")
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
        # TODO: Implement {name}
        pass
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
        workflow_steps.append({
            "name": f"step_{i + 1}",
            "processor": "log",
            "params": {"message": f"Step {i + 1} of {name}"},
        })

    return {
        "workflow": {
            "name": name,
            "description": f"Auto-generated workflow: {name}",
            "version": "1.0",
            "steps": workflow_steps,
            "error_handling": {
                "strategy": "retry",
                "max_attempts": 3,
            },
        }
    }


if __name__ == "__main__":
    cli()
