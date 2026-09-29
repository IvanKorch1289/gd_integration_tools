"""DoD-12 replay gate: реальный Temporal server → execute → Replayer.

Полная цепочка (per W4): скомпилировать project-workflow
(:class:`WorkflowBuilder` → ``compile_workflow`` → registry) → исполнить на
живом Temporal server (``temporal server start-dev``) → выгрузить history →
``TemporalWorkflowBackend.replay()`` (temporalio Replayer) — несовместимость
кода с историей даёт ``WorkflowNonDeterminismError`` → exit 1.

Usage:
    temporal server start-dev --port 7233 --db-file /tmp/temporal-dev.db &
    python tools/checks/temporal_replay_gate.py [--host localhost:7233] \\
        [--history-out dist/temporal/replay_gate_history.json]

Exit codes:
    0 — execute + replay OK;
    1 — FAIL (non-determinism / result mismatch);
    2 — ENV_FAILURE (сервер недоступен) — отличим от code failure (W1).
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import time
from datetime import timedelta
from pathlib import Path
from typing import Any

from temporalio import activity
from temporalio.client import Client
from temporalio.worker import UnsandboxedWorkflowRunner, Worker

ROOT = Path(__file__).resolve().parents[2]
TASK_QUEUE = "replay-gate"


@activity.defn(name="replay_gate.echo")
async def replay_gate_echo(payload: dict[str, Any]) -> dict[str, Any]:
    """Эхо-activity: детерминированный результат для execute-фазы."""
    return {"echo": payload, "marker": "replay-gate-v1"}


async def _run(host: str, history_out: Path | None) -> int:
    from src.backend.dsl.workflow.builder import WorkflowBuilder
    from src.backend.dsl.workflow.compiler.emitter import compile_workflow
    from src.backend.infrastructure.workflow.temporal_backend import (
        TemporalWorkflowBackend,
    )

    decl = (
        WorkflowBuilder("replay.gate.flow")
        .description("DoD-12 replay gate workflow (execute → history → Replayer)")
        .activity("replay_gate.echo", args={"step": 1}, output_key="echo")
        .build()
    )
    compiled = compile_workflow(decl)

    client = await Client.connect(host)
    # Unsandboxed: AST-валидация песочницы реимпортирует модуль эмиттера в
    # изолированном namespace и спотыкается о beartype.claw (circular import
    # в изоляторе, не в проектном коде). Детерминизм гейта обеспечивает
    # Replayer-фаза ниже, а не песочница.
    async with Worker(
        client,
        task_queue=TASK_QUEUE,
        workflows=[compiled.cls],
        activities=[replay_gate_echo],
        workflow_runner=UnsandboxedWorkflowRunner(),
    ):
        handle = await client.start_workflow(
            compiled.cls,
            {"x": 1},
            id=f"replay-gate-{int(time.time())}",
            task_queue=TASK_QUEUE,
            execution_timeout=timedelta(seconds=60),
        )
        result = await handle.result()

    if "echo" not in result.get("outputs", {}):
        print(f"FAIL: outputs missing echo: {result}", file=sys.stderr)
        return 1
    if result["outputs"]["echo"].get("marker") != "replay-gate-v1":
        print(f"FAIL: unexpected echo payload: {result}", file=sys.stderr)
        return 1

    history = await handle.fetch_history()
    history_json = history.to_json()

    if history_out is not None:
        history_out.parent.mkdir(parents=True, exist_ok=True)
        history_out.write_text(history_json, encoding="utf-8")

    backend = TemporalWorkflowBackend(client=client)
    await backend.replay(workflow_name=compiled.name, history=history_json.encode())

    print(
        f"OK: workflow={compiled.name} executed + replayed, "
        f"events={len(history.events)}, history={'saved' if history_out else 'not saved'}"
    )
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="localhost:7233")
    parser.add_argument("--history-out", type=Path, default=None)
    args = parser.parse_args(argv)

    try:
        return asyncio.run(_run(args.host, args.history_out))
    except OSError as exc:
        # ENV_FAILURE: сервер не поднят — не смешивать с code failure (W1).
        print(
            f"ENV_FAILURE: temporal server unreachable at {args.host}: {exc}",
            file=sys.stderr,
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
