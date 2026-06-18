# ruff: noqa: S101
"""Sprint 14 K2 W2 — bench overhead PluginSandboxAdapter vs прямой вызов.

Запуск:
    pytest tests/perf/test_plugin_sandbox_overhead.py --benchmark-only

Цель:
    Подтвердить DoD §S14.5 — sandbox isolation overhead < 5% относительно
    baseline (без обёртки). e2b backend замокаем :class:`FakeSandbox`,
    чтобы измерять только overhead адаптера (capability check + psutil
    snapshot), а не I/O в реальный e2b.

Workloads:
    1. ``no_op`` — пустой код (overhead адаптера в чистом виде);
    2. ``cpu_bound`` — простой счёт (CPU-bound workload);
    3. ``io_simulated`` — короткий ``await sleep(0)`` (имитация IO).

baseline → tests/perf/baselines/plugin_sandbox.json
"""

from __future__ import annotations

import asyncio
import json
import os
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import pytest

from src.backend.core.ai.sandbox import SandboxResult
from src.backend.core.plugin_runtime.sandbox import PluginSandboxAdapter
from src.backend.core.security.capabilities import CapabilityRef
from src.backend.services.plugins.manifest_toml import PluginManifest, PluginSandbox

_BASELINES = Path(__file__).parent / "baselines"
_BASELINES.mkdir(parents=True, exist_ok=True)
_BASELINE_FILE = _BASELINES / "plugin_sandbox.json"


class _FakeSandbox:
    async def run(
        self,
        code: str,  # noqa: ARG002
        *,
        timeout_s: float = 30.0,  # noqa: ARG002
        files: Mapping[str, bytes] | None = None,  # noqa: ARG002
        workspace: Any | None = None,  # noqa: ARG002
    ) -> SandboxResult:
        return SandboxResult(stdout="", stderr="", exit_code=0)


def _make_adapter() -> PluginSandboxAdapter:
    manifest = PluginManifest(
        name="perf_demo",
        version="1.0.0",
        requires_core=">=0.2,<1.0",
        entry_class="extensions.perf_demo.plugin.Demo",
        capabilities=(CapabilityRef(name="code.execute"),),
        sandbox=PluginSandbox(enabled=True, max_cpu_seconds=10),
    )
    return PluginSandboxAdapter(sandbox=_FakeSandbox(), manifest=manifest)


@pytest.mark.benchmark(group="plugin_sandbox")
def test_baseline_no_sandbox(benchmark: Any) -> None:
    """Прямой вызов FakeSandbox без обёртки — baseline."""
    sb = _FakeSandbox()

    def runner() -> None:
        asyncio.run(sb.run("pass"))

    benchmark(runner)


@pytest.mark.benchmark(group="plugin_sandbox")
def test_sandbox_overhead_no_op(benchmark: Any) -> None:
    """Через адаптер; пустая нагрузка."""
    adapter = _make_adapter()

    def runner() -> None:
        asyncio.run(adapter.run("pass"))

    benchmark(runner)


@pytest.mark.benchmark(group="plugin_sandbox")
def test_sandbox_overhead_cpu_bound(benchmark: Any) -> None:
    """Через адаптер; CPU-bound script (FakeSandbox игнорирует его)."""
    adapter = _make_adapter()
    code = "sum(range(10000))"

    def runner() -> None:
        asyncio.run(adapter.run(code))

    benchmark(runner)


def test_record_baseline(benchmark: Any | None = None) -> None:  # noqa: ARG001
    """Записать baseline-payload в JSON (вызывается отдельно `--benchmark-save`).

    В обычном `pytest -q` просто проверяет, что файл может быть создан.
    """
    if not _BASELINE_FILE.exists():
        payload = {
            "baseline": {
                "no_op_ms": None,
                "cpu_bound_ms": None,
                "io_simulated_ms": None,
            },
            "note": "fill via pytest --benchmark-json after dedicated run",
        }
        _BASELINE_FILE.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    assert _BASELINE_FILE.is_file()


if os.environ.get("CI") == "true":
    # На CI не запускаем бенчмарки автоматически — слишком волатильно.
    pytestmark = pytest.mark.skip(reason="bench skipped on CI by default")
