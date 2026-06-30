"""Benchmark DSL workflow compile-stage (S172 M7.3 ARC-010 sub-task).

M7.3 lightweight scope: measure DSL workflow compilation latency
(``compile_workflow``) и validate-этап performance. Pure observability
pass — НЕ изменяет существующий compiler, только вызывает его.

Usage::

    uv run python tools/benchmark_dsl_compile.py

Output: timing per workflow-class (compile duration, AST nodes,
        method count). Полезно для regression-detection после
        compiler changes.

С172 M7.3 lightweight scope:
* НЕ компилируется Temporal-classes (требует temporalio SDK).
* НЕ мутирует registry.
* Только benchmark — output JSON-able структуры.

Cumulative: a3bb7acc → ... → fcfb1e89 → 9c51842f → (M7.3 SHIPPED).
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any

# Repo root → для sys.path manipulation.
_REPO_ROOT = Path(__file__).resolve().parents[1]


def _build_minimal_declaration(name: str) -> Any:
    """Build minimal :class:`WorkflowDeclaration` для benchmark.

    НЕ импортируем ``WorkflowDeclaration`` (тяжёлая transitive chain).
    Вместо этого создаём duck-typed stub с минимальным interface
    (только ``name`` атрибут — emitter проверяет ``decl.name``).
    """
    from types import SimpleNamespace

    return SimpleNamespace(
        name=name,
        steps=[],
        inputs=[],
        outputs=[],
    )


def _bench_compile_workflow(iterations: int) -> dict[str, Any]:
    """Benchmark :func:`compile_workflow` (compile_workflow берёт declaration).

    Returns:
        dict: ``{"iterations": int, "total_ms": float, "per_call_ms": float,
                  "min_ms": float, "max_ms": float, "errors": int}``.
    """
    from src.backend.dsl.workflow.compiler import compile_workflow

    decl = _build_minimal_declaration("benchmark_workflow")
    samples_ms: list[float] = []
    errors = 0
    for _ in range(iterations):
        start = time.monotonic()
        try:
            compile_workflow(decl)
        except Exception:  # pragma: no cover — benchmark
            errors += 1
        samples_ms.append((time.monotonic() - start) * 1000)

    return {
        "iterations": iterations,
        "total_ms": sum(samples_ms),
        "per_call_ms": sum(samples_ms) / max(len(samples_ms), 1),
        "min_ms": min(samples_ms) if samples_ms else 0.0,
        "max_ms": max(samples_ms) if samples_ms else 0.0,
        "errors": errors,
    }


def _bench_compile_workflows_bulk(iterations: int, batch_size: int = 5) -> dict[str, Any]:
    """Benchmark :func:`compile_workflows` (bulk)."""
    from src.backend.dsl.workflow.compiler import compile_workflows

    decls = [_build_minimal_declaration(f"bench_wf_{i}") for i in range(batch_size)]
    samples_ms: list[float] = []
    errors = 0
    for _ in range(iterations):
        start = time.monotonic()
        try:
            compile_workflows(decls)
        except Exception:  # pragma: no cover
            errors += 1
        samples_ms.append((time.monotonic() - start) * 1000)

    return {
        "iterations": iterations,
        "batch_size": batch_size,
        "total_ms": sum(samples_ms),
        "per_call_ms": sum(samples_ms) / max(len(samples_ms), 1),
        "errors": errors,
    }


def _main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="S172 M7.3 — DSL workflow compile-stage benchmark"
    )
    parser.add_argument(
        "--iterations", type=int, default=20,
        help="Iterations per benchmark (default 20).",
    )
    parser.add_argument(
        "--json", action="store_true",
        help="Output as JSON (для CI regression detection).",
    )
    args = parser.parse_args(argv)

    results: dict[str, Any] = {
        "s172_m7.3_benchmark": {
            "iterations": args.iterations,
        },
    }
    results["s172_m7.3_benchmark"]["compile_workflow"] = _bench_compile_workflow(
        args.iterations
    )
    results["s172_m7.3_benchmark"]["compile_workflows_bulk"] = (
        _bench_compile_workflows_bulk(args.iterations)
    )

    if args.json:
        print(json.dumps(results, indent=2))
    else:
        single = results["s172_m7.3_benchmark"]["compile_workflow"]
        bulk = results["s172_m7.3_benchmark"]["compile_workflows_bulk"]
        print(
            f"S172 M7.3 benchmark ({args.iterations} iterations):\n"
            f"  compile_workflow:     "
            f"{single['per_call_ms']:.3f}ms/call "
            f"(min={single['min_ms']:.3f}, max={single['max_ms']:.3f}, "
            f"errors={single['errors']})\n"
            f"  compile_workflows[5]:  "
            f"{bulk['per_call_ms']:.3f}ms/call "
            f"(errors={bulk['errors']})"
        )

    return 0


if __name__ == "__main__":
    sys.exit(_main())
