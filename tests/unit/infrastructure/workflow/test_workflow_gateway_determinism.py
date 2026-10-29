"""ADR-0395 — детерминизм gateway-компиляторов.

Дефект (5, medium): ``compiler/gateways.py`` использовал
``asyncio.gather`` / ``asyncio.wait`` / ``create_task``. Temporal-sandbox
рестритктует ``asyncio.wait``
(``temporalio/worker/workflow_sandbox/_restrictions.py``), а guard
``tools/s86_workflow_sandbox_guard.py`` об этих API молчал («0
violations»). Порядок событий зависел от event-loop, а победитель OR
ветки выбирался по времени завершения (недетерминированно).

Проверяем:
* два прогона дают одинаковый порядок событий (AND и OR);
* победитель OR-ветки выбирается детерминированно;
* в исходниках gateway-компиляторов нет запрещённых примитивов;
* sandbox-guard ловит ``asyncio.wait`` / ``asyncio.gather``.
"""

from __future__ import annotations

import inspect
import textwrap
from pathlib import Path
from typing import Any

import pytest

from src.backend.dsl.workflow.compiler import gateways as gw_compilers
from src.backend.dsl.workflow.gateways import BranchSpec, GatewaySpec
from src.backend.dsl.workflow.spec import ActivityDeclaration

_REPO_ROOT = Path(__file__).resolve().parents[4]


def _gateway_decl(kind: str, branch_names: list[str]) -> Any:
    """ActivityDeclaration с gateway-спецификацией."""
    from src.backend.dsl.workflow.builder import WorkflowBuilder

    builder = WorkflowBuilder(f"{kind}.flow")
    branches = [
        BranchSpec(
            name=name, condition=None, steps=[ActivityDeclaration(name=f"step.{name}")]
        )
        for name in branch_names
    ]
    spec = GatewaySpec(kind=kind, branches=branches)  # type: ignore[arg-type]
    if kind == "and":
        builder.gateway_and(*branches)
    elif kind == "or":
        builder.gateway_or(*branches)
    else:  # pragma: no cover — defensive
        raise AssertionError(f"unsupported kind {kind}")
    del spec
    return builder._steps[-1]


@pytest.fixture
def _record_events(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Подменить step-компилятор активности на запись событий."""
    events: list[str] = []

    async def _fake_compile_activity_step(
        decl: ActivityDeclaration, ctx: dict[str, Any]
    ) -> str:
        events.append(f"start:{decl.name}")
        return decl.name

    import src.backend.dsl.workflow.compiler.step_compilers as sc

    monkeypatch.setattr(sc, "compile_activity_step", _fake_compile_activity_step)
    return events


class TestGatewayDeterminism:
    """Двукратный запуск → одинаковый порядок событий."""

    @pytest.mark.asyncio
    async def test_and_gateway_event_order_is_stable(
        self, _record_events: list[str]
    ) -> None:
        """AND-gateway: порядок событий совпадает между прогонами."""
        decl = _gateway_decl("and", ["alpha", "beta", "gamma"])

        await gw_compilers.compile_and(decl, {})
        first_run = list(_record_events)
        _record_events.clear()

        await gw_compilers.compile_and(decl, {})
        second_run = list(_record_events)

        assert first_run == second_run
        assert first_run == ["start:step.alpha", "start:step.beta", "start:step.gamma"]

    @pytest.mark.asyncio
    async def test_or_gateway_event_order_is_stable(
        self, _record_events: list[str]
    ) -> None:
        """OR-gateway: порядок событий и победитель совпадают между прогонами."""
        decl = _gateway_decl("or", ["alpha", "beta"])

        first_result = await gw_compilers.compile_or(decl, {})
        first_run = list(_record_events)
        _record_events.clear()

        second_result = await gw_compilers.compile_or(decl, {})
        second_run = list(_record_events)

        assert first_run == second_run
        assert first_result == second_result == "step.alpha"

    @pytest.mark.asyncio
    async def test_or_gateway_picks_first_branch_in_declaration_order(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Победитель OR — первая ветка в порядке объявления (не по времени)."""
        import asyncio

        events: list[str] = []

        async def _fake_compile_activity_step(
            decl: ActivityDeclaration, ctx: dict[str, Any]
        ) -> str:
            events.append(decl.name)
            # Одинаковая длительность → обе ветки завершаются в одном
            # event-loop тике; победитель не должен зависеть от того,
            # какая ветка «случайно» финишировала первой.
            await asyncio.sleep(0)
            return decl.name

        import src.backend.dsl.workflow.compiler.step_compilers as sc

        monkeypatch.setattr(sc, "compile_activity_step", _fake_compile_activity_step)

        decl = _gateway_decl("or", ["alpha", "beta"])
        result = await gw_compilers.compile_or(decl, {})

        assert result == "step.alpha"
        assert events == ["step.alpha", "step.beta"]


class TestSandboxSafeGateways:
    """В gateway-компиляторах нет недетерминированных asyncio-примитивов."""

    def test_gateway_module_has_no_forbidden_primitives(self) -> None:
        """В ``gateways.py`` нет ``asyncio.wait`` / ``asyncio.gather``."""
        source = inspect.getsource(gw_compilers)

        assert "asyncio.wait(" not in source
        assert "asyncio.gather(" not in source
        assert "asyncio.as_completed(" not in source
        assert "workflow.wait(" in source

    def test_sandbox_guard_detects_asyncio_wait(self, tmp_path: Path) -> None:
        """Guard ловит ``asyncio.wait`` внутри ``compile_*``-функции."""
        from tools.s86_workflow_sandbox_guard import scan_file

        module = tmp_path / "mod.py"
        module.write_text(
            textwrap.dedent(
                """\
                import asyncio

                async def compile_or(decl, ctx):
                    done, pending = await asyncio.wait(tasks, return_when=asyncio.FIRST_COMPLETED)
                    return done
                """
            ),
            encoding="utf-8",
        )

        violations = scan_file(module)

        assert violations, "guard обязан ловить asyncio.wait внутри compile_*"
        assert any("asyncio.wait" in reason for _line, _text, reason in violations)

    def test_sandbox_guard_detects_asyncio_gather(self, tmp_path: Path) -> None:
        """Guard ловит ``asyncio.gather`` внутри ``compile_*``-функции."""
        from tools.s86_workflow_sandbox_guard import scan_file

        module = tmp_path / "mod.py"
        module.write_text(
            textwrap.dedent(
                """\
                import asyncio

                async def compile_and(decl, ctx):
                    return await asyncio.gather(*coros)
                """
            ),
            encoding="utf-8",
        )

        violations = scan_file(module)

        assert violations, "guard обязан ловить asyncio.gather внутри compile_*"
        assert any("asyncio.gather" in reason for _line, _text, reason in violations)

    def test_guard_passes_on_current_compiler_sources(self) -> None:
        """Текущие исходники workflow-компиляторов — 0 violations."""
        from tools.s86_workflow_sandbox_guard import scan_file

        compiler_dir = _REPO_ROOT / "src" / "backend" / "dsl" / "workflow" / "compiler"
        violations: list[tuple[Path, int, str, str]] = []
        for py_file in sorted(compiler_dir.rglob("*.py")):
            for line_no, text, reason in scan_file(py_file):
                violations.append((py_file, line_no, text, reason))

        assert violations == []
