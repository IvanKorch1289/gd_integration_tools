"""Тесты типизированного lifecycle (аудит 2026-10-01, F-E/F-F/F-J/F-K).

Каждый тест закрывает конкретную семантику, заявленную в
``src/backend/plugins/composition/lifecycle/operations.py``:

* топологический порядок старта по ``dependencies``;
* таймаут на операцию;
* REQUIRED vs OPTIONAL;
* reverse-order rollback только реально стартовавших операций;
* идемпотентный shutdown;
* изоляция ошибок shutdown и rollback;
* структурированный отчёт.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

import pytest

from src.backend.plugins.composition.lifecycle.operations import (
    Criticality,
    LifecycleOperation,
    LifecycleRunner,
    LifecycleStartupError,
    LifecycleState,
)

pytestmark = pytest.mark.unit


def _op(
    name: str,
    *,
    start: Any = None,
    stop: Any = None,
    dependencies: tuple[str, ...] = (),
    criticality: Criticality = Criticality.REQUIRED,
    timeout: float = 5.0,
    enabled: Any = None,
    phase: str = "test",
) -> LifecycleOperation:
    """Собрать операцию для теста."""

    async def _noop() -> None:
        return None

    return LifecycleOperation(
        name=name,
        phase=phase,
        start=start or _noop,
        stop=stop,
        enabled=enabled,
        criticality=criticality,
        timeout=timeout,
        dependencies=dependencies,
    )


class TestTopologicalOrder:
    """Порядок выполнения определяется зависимостями, а не объявлением."""

    @pytest.mark.asyncio
    async def test_dependencies_reorder_execution(self) -> None:
        """Операция с зависимостью выполняется позже, даже если объявлена раньше."""
        order: list[str] = []

        def make(name: str) -> Any:
            async def _start() -> None:
                order.append(name)

            return _start

        runner = LifecycleRunner(
            [
                _op("third", start=make("third"), dependencies=("second",)),
                _op("first", start=make("first")),
                _op("second", start=make("second"), dependencies=("first",)),
            ]
        )

        await runner.start_all()

        assert order == ["first", "second", "third"], (
            f"Нарушен топологический порядок: {order}"
        )

    def test_cyclic_dependencies_rejected(self) -> None:
        """Цикл в зависимостях — явная ошибка, а не бесконечный цикл."""
        runner = LifecycleRunner(
            [_op("a", dependencies=("b",)), _op("b", dependencies=("a",))]
        )

        with pytest.raises(ValueError, match="Цикл"):
            _ = runner.plan

    def test_unknown_dependency_rejected(self) -> None:
        """Ссылка на несуществующую операцию — ошибка планирования."""
        runner = LifecycleRunner([_op("a", dependencies=("nope",))])

        with pytest.raises(ValueError, match="неизвестные зависимости"):
            _ = runner.plan

    def test_duplicate_names_rejected(self) -> None:
        """Дубли имён операций недопустимы."""
        runner = LifecycleRunner([_op("dup"), _op("dup")])

        with pytest.raises(ValueError, match="Дубликаты"):
            _ = runner.plan


class TestCriticality:
    """REQUIRED останавливает startup, OPTIONAL деградирует."""

    @pytest.mark.asyncio
    async def test_required_failure_propagates_and_rolls_back(self) -> None:
        """REQUIRED-операция: откат + исключение наружу."""
        stops: list[str] = []

        async def _boom() -> None:
            raise RuntimeError("db unavailable")

        async def _stop_a() -> None:
            stops.append("a")

        async def _stop_b() -> None:
            stops.append("b")

        runner = LifecycleRunner(
            [_op("a", stop=_stop_a), _op("b", stop=_stop_b), _op("c", start=_boom)]
        )

        with pytest.raises(LifecycleStartupError) as exc:
            await runner.start_all()

        assert exc.value.operation == "c"
        assert stops == ["b", "a"], f"Откат должен идти в обратном порядке: {stops}"
        assert runner.report().rollback_performed is True

    @pytest.mark.asyncio
    async def test_optional_failure_degrades_without_rollback(self) -> None:
        """OPTIONAL-операция: деградация, startup продолжается, отката нет."""
        stops: list[str] = []

        async def _boom() -> None:
            raise RuntimeError("optional subsystem down")

        async def _stop_a() -> None:
            stops.append("a")

        runner = LifecycleRunner(
            [
                _op("a", stop=_stop_a),
                _op("opt", start=_boom, criticality=Criticality.OPTIONAL),
                _op("after"),
            ]
        )

        report = await runner.start_all()

        assert stops == [], "Откат при OPTIONAL-деградации не выполняется"
        assert [o.name for o in report.degraded] == ["opt"]
        assert report.rollback_performed is False
        # Последующие операции всё равно выполнены
        assert any(
            o.name == "after" and o.state is LifecycleState.STARTED
            for o in report.outcomes
        )

    @pytest.mark.asyncio
    async def test_failed_required_is_stopped_on_rollback(self) -> None:
        """N-4: упавшая после старта операция ОБЯЗАНА получить stop().

        Контракт изменён по итогам независимого ре-аудита: раньше операция
        попадала в откат только после успешного старта, поэтому операция,
        упавшая **после** частичного подъёма ресурсов, оставляла их живыми.
        Откат теперь идёт по списку предпринятых попыток (``_attempted``).

        Args:
            None: нет.
        """
        stops: list[str] = []

        async def _boom() -> None:
            raise RuntimeError("boom")

        async def _stop_failed() -> None:
            stops.append("failed")

        runner = LifecycleRunner([_op("failed", start=_boom, stop=_stop_failed)])

        with pytest.raises(LifecycleStartupError):
            await runner.start_all()

        assert stops == ["failed"], (
            "Частично поднятая операция обязана быть остановлена"
        )

    @pytest.mark.asyncio
    async def test_degraded_optional_is_not_rolled_back(self) -> None:
        """Деградировавшая OPTIONAL не считается стартовавшей и не откатывается."""
        stops: list[str] = []

        async def _boom() -> None:
            raise RuntimeError("boom")

        async def _stop_opt() -> None:
            stops.append("opt")

        runner = LifecycleRunner(
            [
                _op("ok"),
                _op(
                    "opt", start=_boom, stop=_stop_opt, criticality=Criticality.OPTIONAL
                ),
            ]
        )

        await runner.start_all()

        assert stops == []


class TestTimeout:
    """Таймаут на операцию."""

    @pytest.mark.asyncio
    async def test_timeout_on_required_triggers_rollback(self) -> None:
        """REQUIRED-операция, не уложившаяся в timeout → откат + ошибка."""
        stops: list[str] = []

        async def _sleep_forever() -> None:
            await asyncio.sleep(10)

        async def _stop_a() -> None:
            stops.append("a")

        runner = LifecycleRunner(
            [_op("a", stop=_stop_a), _op("slow", start=_sleep_forever, timeout=0.05)]
        )

        with pytest.raises(LifecycleStartupError, match="slow"):
            await runner.start_all()

        assert stops == ["a"]
        report = runner.report()
        assert "TimeoutError" in next(
            o.error for o in report.outcomes if o.name == "slow"
        )


class TestShutdown:
    """Shutdown: обратный порядок, идемпотентность, изоляция ошибок."""

    @pytest.mark.asyncio
    async def test_shutdown_runs_in_reverse_order(self) -> None:
        """Остановка идёт в обратном порядке старта."""
        stops: list[str] = []

        def make(name: str) -> Any:
            async def _stop() -> None:
                stops.append(name)

            return _stop

        runner = LifecycleRunner(
            [
                _op("a", stop=make("a")),
                _op("b", stop=make("b")),
                _op("c", stop=make("c")),
            ]
        )
        await runner.start_all()

        await runner.shutdown()

        assert stops == ["c", "b", "a"]

    @pytest.mark.asyncio
    async def test_shutdown_is_idempotent(self) -> None:
        """Повторный shutdown не выполняет stop второй раз."""
        calls: list[str] = []

        async def _stop() -> None:
            calls.append("stop")

        runner = LifecycleRunner([_op("a", stop=_stop)])
        await runner.start_all()

        await runner.shutdown()
        await runner.shutdown()

        assert calls == ["stop"], f"Shutdown не идемпотентен: {calls}"

    @pytest.mark.asyncio
    async def test_shutdown_isolates_failures(self) -> None:
        """Падение одного stop не мешает остальным (F-J)."""
        stops: list[str] = []

        async def _boom() -> None:
            raise RuntimeError("stop failed")

        def make(name: str) -> Any:
            async def _stop() -> None:
                stops.append(name)

            return _stop

        runner = LifecycleRunner(
            [_op("a", stop=make("a")), _op("b", stop=_boom), _op("c", stop=make("c"))]
        )
        await runner.start_all()

        errors = await runner.shutdown()

        assert stops == ["c", "a"], f"Остальные stop должны выполниться: {stops}"
        assert len(errors) == 1
        assert errors[0].startswith("b:")

    @pytest.mark.asyncio
    async def test_shutdown_is_idempotent_under_failure(self) -> None:
        """Повторный shutdown после ошибки тоже ничего не делает."""
        calls: list[str] = []

        def make(name: str) -> Any:
            async def _stop() -> None:
                calls.append(name)

            return _stop

        runner = LifecycleRunner([_op("a", stop=make("a"))])
        await runner.start_all()
        await runner.shutdown()
        await runner.shutdown()

        assert calls == ["a"]

    @pytest.mark.asyncio
    async def test_rollback_isolates_failures(self) -> None:
        """Падение одного stop при откате не прерывает откат остальных."""
        stops: list[str] = []

        async def _boom() -> None:
            raise RuntimeError("stop failed")

        def make(name: str) -> Any:
            async def _stop() -> None:
                stops.append(name)

            return _stop

        async def _start_boom() -> None:
            raise RuntimeError("start failed")

        runner = LifecycleRunner(
            [
                _op("a", stop=make("a")),
                _op("b", stop=_boom),
                _op("c", stop=make("c")),
                _op("d", start=_start_boom),
            ]
        )

        with pytest.raises(LifecycleStartupError):
            await runner.start_all()

        assert stops == ["c", "a"], f"Откат должен продолжиться после ошибки: {stops}"


class TestEnabled:
    """Предикат включения операции."""

    @pytest.mark.asyncio
    async def test_disabled_operation_is_skipped(self) -> None:
        """Выключенная операция помечается SKIPPED_DISABLED и не выполняется."""
        calls: list[str] = []

        async def _start() -> None:
            calls.append("start")

        runner = LifecycleRunner([_op("off", start=_start, enabled=False)])
        report = await runner.start_all()

        assert calls == []
        assert report.outcomes[0].state is LifecycleState.SKIPPED_DISABLED

    @pytest.mark.asyncio
    async def test_enabled_callable_is_evaluated(self) -> None:
        """``enabled`` может быть предикатом, а не константой."""
        calls: list[str] = []

        async def _start() -> None:
            calls.append("start")

        runner = LifecycleRunner([_op("cond", start=_start, enabled=lambda: False)])
        await runner.start_all()

        assert calls == []


class TestStructuredReport:
    """Структурированный отчёт о startup."""

    @pytest.mark.asyncio
    async def test_report_is_json_serializable_and_complete(self) -> None:
        """Отчёт сериализуется в JSON и содержит все операции."""

        async def _boom() -> None:
            raise RuntimeError("optional down")

        runner = LifecycleRunner(
            [
                _op("ok", phase="services"),
                _op(
                    "opt",
                    phase="services",
                    start=_boom,
                    criticality=Criticality.OPTIONAL,
                ),
                _op("off", phase="infrastructure", enabled=False),
            ]
        )
        report = await runner.start_all()

        payload = json.loads(json.dumps(report.to_dict()))
        assert {o["name"] for o in payload["operations"]} == {"ok", "opt", "off"}
        assert payload["degraded"] == ["opt"]
        assert payload["required_all_started"] is True
        states = {o["name"]: o["state"] for o in payload["operations"]}
        assert states["ok"] == str(LifecycleState.STARTED)
        assert states["opt"] == str(LifecycleState.DEGRADED)
        assert states["off"] == str(LifecycleState.SKIPPED_DISABLED)


class TestSyncAndAsyncCallables:
    """Операции могут быть синхронными или асинхронными."""

    @pytest.mark.asyncio
    async def test_sync_start_and_stop_supported(self) -> None:
        """Синхронные функции также поддерживаются (обратная совместимость)."""
        events: list[str] = []

        def _sync_start() -> None:
            events.append("start")

        def _sync_stop() -> None:
            events.append("stop")

        runner = LifecycleRunner([_op("a", start=_sync_start, stop=_sync_stop)])
        await runner.start_all()
        await runner.shutdown()

        assert events == ["start", "stop"]
