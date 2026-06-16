"""CLI debug command — инструменты отладки DSL маршрутов и процессоров.

Wave [wave:h2-cli-debug]
K-ARCH-2: CLI tooling for developer experience.
"""

from __future__ import annotations

import json
import sys
import traceback
from pathlib import Path
from typing import Any

import click

# Add parent to path for imports
CLI_DIR = Path(__file__).parent
DSL_DIR = CLI_DIR.parent
BACKEND_DIR = DSL_DIR.parent
SRC_DIR = BACKEND_DIR.parent
sys.path.insert(0, str(SRC_DIR))

from src.backend.dsl.engine.exchange import (  # noqa: E402
    Exchange,
    ExchangeStatus,
    Message,
)
from src.backend.dsl.engine.processors.base import BaseProcessor  # noqa: E402


@click.group()
def cli() -> None:
    """DSL Debug CLI tools."""
    pass


@cli.command("validate-route")
@click.argument("route_file", type=click.Path(exists=True))
@click.option("--format", "-f", default="yaml", help="Format (yaml, json)")
def validate_route(route_file: str, format: str) -> None:
    """Validate a DSL route file.

    ROUTE_FILE: Path to the route YAML file.
    """
    try:
        from src.backend.dsl.yaml_loader import (  # type: ignore[attr-defined]
            YamlRouteLoader,
        )

        loader = YamlRouteLoader()
        route = loader.load_file(Path(route_file))

        if format == "json":
            click.echo(
                json.dumps({"valid": True, "route_id": route.get("id")}, indent=2)
            )
        else:
            click.echo(f"✓ Route '{route.get('id')}' is valid")
            click.echo(f"  Source: {route.get('source', {}).get('type')}")
            click.echo(f"  Steps: {len(route.get('steps', []))}")

    except Exception as exc:
        if format == "json":
            click.echo(json.dumps({"valid": False, "error": str(exc)}, indent=2))
        else:
            click.echo(f"✗ Validation failed: {exc}", err=True)
            sys.exit(1)


@cli.command("dry-run")
@click.argument("route_file", type=click.Path(exists=True))
@click.option("--body", "-b", default=None, help="Request body (JSON string)")
@click.option("--headers", "-h", default=None, help="Request headers (JSON string)")
@click.option("--verbose", "-v", is_flag=True, help="Verbose output")
def dry_run(
    route_file: str, body: str | None, headers: str | None, verbose: bool
) -> None:
    """Perform a dry run of a route.

    ROUTE_FILE: Path to the route YAML file.
    """
    try:
        from src.backend.dsl.engine.dry_run import (  # type: ignore[attr-defined]
            DryRunner,
        )
        from src.backend.dsl.yaml_loader import (  # type: ignore[attr-defined]
            YamlRouteLoader,
        )

        loader = YamlRouteLoader()
        route = loader.load_file(Path(route_file))

        body_data = json.loads(body) if body else {"test": "data"}
        headers_data = json.loads(headers) if headers else {}

        runner = DryRunner()
        result = runner.run(route, body=body_data, headers=headers_data)

        if verbose:
            click.echo(f"Route: {route.get('id')}")
            click.echo(f"Status: {result.get('status')}")
            click.echo(f"Duration: {result.get('duration_ms', 0):.2f}ms")
            click.echo(f"Steps executed: {result.get('steps_executed', 0)}")

            if result.get("trace"):
                click.echo("\nTrace:")
                for step in result.get("trace", []):
                    click.echo(f"  - {step}")
        else:
            click.echo(json.dumps(result, indent=2))

    except Exception as exc:
        click.echo(f"✗ Dry run failed: {exc}", err=True)
        if verbose:
            traceback.print_exc()
        sys.exit(1)


@cli.command("inspect-exchange")
@click.argument("exchange_json", type=str)
@click.option("--verbose", "-v", is_flag=True, help="Verbose output")
def inspect_exchange(exchange_json: str, verbose: bool) -> None:
    """Inspect an exchange JSON representation.

    EXCHANGE_JSON: JSON string representing an exchange.
    """
    try:
        data = json.loads(exchange_json)
        exchange = _reconstruct_exchange(data)

        if verbose:
            click.echo(f"Status: {exchange.status.value}")
            click.echo(f"In message: {exchange.in_message.body}")
            click.echo(f"Out message: {exchange.out_message}")
            click.echo(f"Properties: {list(exchange.properties.keys())}")
            click.echo(f"Meta: route_id={exchange.meta.route_id}")
        else:
            click.echo(
                json.dumps(
                    {
                        "status": exchange.status.value,
                        "has_in_message": exchange.in_message is not None,
                        "has_out_message": exchange.out_message is not None,
                        "property_count": len(exchange.properties),
                    },
                    indent=2,
                )
            )

    except Exception as exc:
        click.echo(f"✗ Inspection failed: {exc}", err=True)
        sys.exit(1)


@cli.command("trace-pipeline")
@click.argument("pipeline_file", type=click.Path(exists=True))
@click.option(
    "--output", "-o", type=click.Path(), default=None, help="Output file for trace"
)
def trace_pipeline(pipeline_file: str, output: str | None) -> None:
    """Trace pipeline execution steps.

    PIPELINE_FILE: Path to pipeline JSON/YAML definition.
    """
    try:
        from src.backend.dsl.yaml_loader import (  # type: ignore[attr-defined]
            YamlRouteLoader,
        )

        loader = YamlRouteLoader()
        route = loader.load_file(Path(pipeline_file))

        trace_result = _trace_pipeline_steps(route)

        if output:
            with open(output, "w") as f:
                json.dump(trace_result, f, indent=2)
            click.echo(f"Trace written to: {output}")
        else:
            click.echo(json.dumps(trace_result, indent=2))

    except Exception as exc:
        click.echo(f"✗ Trace failed: {exc}", err=True)
        sys.exit(1)


@cli.command("lint-route")
@click.argument("route_file", type=click.Path(exists=True))
@click.option("--verbose", "-v", is_flag=True, help="Verbose output")
def lint_route(route_file: str, verbose: bool) -> None:
    """Lint a route file for common issues.

    ROUTE_FILE: Path to the route YAML file.
    """
    try:
        from src.backend.dsl.engine.linter import DSLLinter

        linter = DSLLinter()
        issues = linter.lint_file(Path(route_file))  # type: ignore[attr-defined]

        if not issues:
            click.echo(f"✓ No issues found in {route_file}")
        else:
            click.echo(f"✗ Found {len(issues)} issue(s):")
            for issue in issues:
                severity = "ERROR" if issue.severity == "ERROR" else "WARNING"
                click.echo(f"  [{severity}] {issue.code}: {issue.message}")
                if verbose and issue.line:
                    click.echo(f"         at line {issue.line}")

            sys.exit(1 if any(i.severity == "ERROR" for i in issues) else 0)

    except Exception as exc:
        click.echo(f"✗ Lint failed: {exc}", err=True)
        sys.exit(1)


@cli.command("explain-processor")
@click.argument("processor_class", type=str)
@click.option("--verbose", "-v", is_flag=True, help="Verbose output")
def explain_processor(processor_class: str, verbose: bool) -> None:
    """Explain a processor's structure and behavior.

    PROCESSOR_CLASS: Full class name (e.g., 'HttpCallProcessor').
    """
    try:
        info = _get_processor_info(processor_class)

        if verbose:
            click.echo(f"Processor: {info['name']}")
            click.echo(f"Type: {info['type']}")
            click.echo(f"Category: {info['category']}")
            click.echo(f"Side Effect: {info['side_effect']}")
            click.echo(f"Compensatable: {info['compensatable']}")
            click.echo("\nDocstring:")
            click.echo(f"  {info.get('docstring', 'No docstring')}")
            click.echo("\nParameters:")
            for param, ptype in info.get("params", {}).items():
                click.echo(f"  - {param}: {ptype}")
        else:
            click.echo(json.dumps(info, indent=2))

    except Exception as exc:
        click.echo(f"✗ Failed to explain processor: {exc}", err=True)
        sys.exit(1)


def _reconstruct_exchange(data: dict[str, Any]) -> Exchange[Any]:
    """Reconstruct an Exchange object from serialized data."""
    in_msg = None
    if data.get("in_message"):
        in_msg = Message(
            body=data["in_message"].get("body"),
            headers=data["in_message"].get("headers", {}),
        )

    exchange = Exchange(in_message=in_msg or Message(body=None, headers={}))
    exchange.status = ExchangeStatus(data.get("status", "pending"))
    return exchange


def _trace_pipeline_steps(route: dict[str, Any]) -> dict[str, Any]:
    """Trace through pipeline steps."""
    steps = route.get("steps", [])
    trace = []

    for i, step in enumerate(steps):
        trace.append(
            {
                "index": i,
                "name": step.get("name", f"step_{i}"),
                "type": step.get("type", "unknown"),
                "params": step.get("params", {}),
            }
        )

    return {
        "route_id": route.get("id", "unknown"),
        "total_steps": len(steps),
        "trace": trace,
    }


def _get_processor_info(processor_class: str) -> dict[str, Any]:
    """Get processor information by class name."""
    # Try to import from known processor modules
    modules_to_try = [
        "src.backend.dsl.engine.processors.core",
        "src.backend.dsl.engine.processors.ai_processors",
        "src.backend.dsl.engine.processors.components",
        "src.backend.dsl.engine.processors.business",
    ]

    for module_name in modules_to_try:
        try:
            import importlib

            module = importlib.import_module(module_name)
            if hasattr(module, processor_class):
                cls = getattr(module, processor_class)
                proc = cls()

                return {
                    "name": processor_class,
                    "type": type(proc).__name__,
                    "category": module_name.split(".")[-1],
                    "side_effect": str(proc.side_effect),
                    "compensatable": proc.compensatable,
                    "docstring": cls.__doc__ or "No docstring",
                    "params": _extract_params(cls),
                }
        except (ImportError, AttributeError):
            continue

    raise ValueError(f"Processor '{processor_class}' not found")


def _extract_params(cls: type[BaseProcessor]) -> dict[str, str]:
    """Extract __init__ parameters from a processor class."""
    import inspect

    params = {}
    try:
        sig = inspect.signature(cls.__init__)
        for name, param in sig.parameters.items():
            if name == "self":
                continue
            params[name] = (
                str(param.annotation)
                if param.annotation != inspect.Parameter.empty
                else "Any"
            )
    except (ValueError, TypeError):
        pass
    return params


if __name__ == "__main__":
    cli()
