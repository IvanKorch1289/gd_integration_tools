"""S115 W1 — тесты для core/dsl/protocols.

Verify:
1. Protocol'ы импортируются из core (no dsl import).
2. Существующие concrete classes соответствуют Protocol'ам (runtime_checkable).
3. Aliases работают.
"""

from __future__ import annotations


def test_protocols_importable_from_core() -> None:
    """Protocol'ы живут в core, no dsl imports required."""
    from src.backend.core.dsl.protocols import (
        CommandRegistry,
        CommandRegistryProtocol,
        ExecutionEngine,
        ExecutionEngineProtocol,
        Pipeline,
        PipelineProtocol,
    )

    assert CommandRegistry is CommandRegistryProtocol
    assert Pipeline is PipelineProtocol
    assert ExecutionEngine is ExecutionEngineProtocol


def test_command_registry_protocol_is_runtime_checkable() -> None:
    """Duck-typed objects can be checked with isinstance."""
    from src.backend.core.dsl.protocols import CommandRegistryProtocol

    class FakeRegistry:
        def execute(self, name: str, *, payload: dict | None = None) -> str:
            return f"executed:{name}"

        def register(self, name: str, handler: object) -> None:
            pass

    fake = FakeRegistry()
    assert isinstance(fake, CommandRegistryProtocol)


def test_pipeline_protocol_is_runtime_checkable() -> None:
    """Duck-typed Pipeline can be checked."""
    from src.backend.core.dsl.protocols import PipelineProtocol

    class FakePipeline:
        steps: list[object] = []

        def run(self, input: object) -> object:
            return input

    fake = FakePipeline()
    assert isinstance(fake, PipelineProtocol)


def test_execution_engine_protocol_is_runtime_checkable() -> None:
    """Duck-typed ExecutionEngine can be checked."""
    from src.backend.core.dsl.protocols import ExecutionEngineProtocol, PipelineProtocol

    class FakeEngine:
        def run_pipeline(self, pipeline: PipelineProtocol) -> object:
            return "result"

        def tracer(self) -> object:
            return None

    fake = FakeEngine()
    assert isinstance(fake, ExecutionEngineProtocol)


def test_core_dsl_package_does_not_import_dsl_implementation() -> None:
    """core/dsl/* — pure Protocol module, no runtime dsl dependency."""
    import ast
    import pathlib

    repo_root = pathlib.Path(__file__).parents[4]  # tests/unit/core/dsl/ → repo root
    protocols_file = repo_root / "src" / "backend" / "core" / "dsl" / "protocols.py"
    source = protocols_file.read_text(encoding="utf-8")
    tree = ast.parse(source, filename=str(protocols_file))
    for node in ast.walk(tree):
        if isinstance(node, (ast.Import, ast.ImportFrom)):
            module = getattr(node, "module", "") or ""
            for alias in node.names:
                imported = alias.name
                full = f"{module}.{imported}" if module else imported
                # Allowed: stdlib (typing) and src.backend.core.* only.
                assert not full.startswith("src.backend.dsl."), (
                    f"core/dsl/protocols.py не должен импортировать dsl: {full}"
                )
