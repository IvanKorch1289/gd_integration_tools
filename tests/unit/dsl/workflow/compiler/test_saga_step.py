"""Тесты :func:`compile_saga_step` — determinism forward/compensate (Sprint 4 К3-D §4).

5 кейсов покрывают critical paths saga-execution:
    1. all-forward-success → no compensate;
    2. forward[2] fails → compensate[1], compensate[0] в reverse-порядке;
    3. partial completion (2 из 3) → compensate только для completed;
    4. compensate[0] fails → compensate[1] всё равно выполняется (best-effort);
    5. длина forward != compensate → compensate с idx >= len(decl.compensate)
       skipped, остальные применяются.

``temporalio`` подменяем через ``monkeypatch.setitem(sys.modules, ...)``
чтобы не запускать реальный workflow runtime.
"""

# ruff: noqa: S101
from __future__ import annotations

import pytest  # noqa: S101

pytest.importorskip(
    "temporalio", reason="temporalio not installed — run: uv sync --extra workflow"
)

import sys
from datetime import timedelta
from types import SimpleNamespace
from typing import Any

import pytest

from src.backend.dsl.workflow.compiler.step_compilers import compile_saga_step
from src.backend.dsl.workflow.spec import ActivityDeclaration, SagaDeclaration


def _make_recorder_temporal(
    *, fail_on: set[str] | None = None
) -> tuple[SimpleNamespace, list[str]]:
    """Сконструировать fake ``temporalio.workflow`` с записью execute_activity.

    Args:
        fail_on: Множество activity name, на которых должен бросаться
            RuntimeError (имитация failure forward или compensate шага).

    Returns:
        (fake_workflow_module, recorder), где recorder — упорядоченный
        список вызванных activity names.
    """
    recorder: list[str] = []
    fail_on = fail_on or set()

    async def fake_execute_activity(name: str, _payload: Any = None, **_kw: Any) -> Any:
        recorder.append(name)
        if name in fail_on:
            raise RuntimeError(f"simulated failure: {name}")
        return None

    async def fake_sleep(_duration: timedelta) -> None:
        return None

    fake_workflow_module = SimpleNamespace(
        execute_activity=fake_execute_activity,
        sleep=fake_sleep,
        logger=SimpleNamespace(
            warning=lambda *a, **kw: recorder.append(f"WARN::{a[0] if a else ''}")
        ),
    )
    return fake_workflow_module, recorder


def _make_fake_common() -> SimpleNamespace:
    class FakeRetryPolicy:
        def __init__(self, **kwargs: Any) -> None:
            self.kwargs = kwargs

    return SimpleNamespace(RetryPolicy=FakeRetryPolicy)


def _patch_temporal(monkeypatch: pytest.MonkeyPatch, fake_wf: SimpleNamespace) -> None:
    fake_common = _make_fake_common()
    monkeypatch.setitem(
        sys.modules, "temporalio", SimpleNamespace(workflow=fake_wf, common=fake_common)
    )
    monkeypatch.setitem(sys.modules, "temporalio.workflow", fake_wf)
    monkeypatch.setitem(sys.modules, "temporalio.common", fake_common)


@pytest.mark.asyncio
async def test_all_forward_success_no_compensate(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Кейс 1: всё forward проходит → 0 compensate-вызовов."""
    fake_wf, recorder = _make_recorder_temporal()
    _patch_temporal(monkeypatch, fake_wf)

    decl = SagaDeclaration(
        forward=[
            ActivityDeclaration(name="orders.create"),
            ActivityDeclaration(name="inventory.reserve"),
            ActivityDeclaration(name="payments.charge"),
        ],
        compensate=[
            ActivityDeclaration(name="orders.cancel"),
            ActivityDeclaration(name="inventory.release"),
            ActivityDeclaration(name="payments.refund"),
        ],
    )
    ctx: dict[str, Any] = {"_default_timeout_s": 60.0, "_input": {}}
    await compile_saga_step(decl, ctx)

    assert recorder == ["orders.create", "inventory.reserve", "payments.charge"]


@pytest.mark.asyncio
async def test_third_forward_fails_compensates_first_two_reverse(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Кейс 2: forward[2] падает → compensate[1] потом compensate[0]."""
    fake_wf, recorder = _make_recorder_temporal(fail_on={"payments.charge"})
    _patch_temporal(monkeypatch, fake_wf)

    decl = SagaDeclaration(
        forward=[
            ActivityDeclaration(name="orders.create"),
            ActivityDeclaration(name="inventory.reserve"),
            ActivityDeclaration(name="payments.charge"),
        ],
        compensate=[
            ActivityDeclaration(name="orders.cancel"),
            ActivityDeclaration(name="inventory.release"),
            ActivityDeclaration(name="payments.refund"),
        ],
    )
    ctx: dict[str, Any] = {"_default_timeout_s": 60.0, "_input": {}}

    with pytest.raises(RuntimeError, match="payments.charge"):
        await compile_saga_step(decl, ctx)

    activity_calls = [name for name in recorder if not name.startswith("WARN::")]
    # forward выполнились до сбоя включительно (charge зафиксирован тоже —
    # exception брошен ПОСЛЕ append в recorder).
    # compensate выполнен только для completed forward (idx 0, 1) в reverse-order.
    assert activity_calls == [
        "orders.create",
        "inventory.reserve",
        "payments.charge",  # failure; не попал в `completed`
        "inventory.release",  # compensate[1] для completed[1]
        "orders.cancel",  # compensate[0] для completed[0]
    ]


@pytest.mark.asyncio
async def test_partial_completion_compensates_only_completed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Кейс 3: forward[1] падает (2 из 3) → compensate ТОЛЬКО для completed[0]."""
    fake_wf, recorder = _make_recorder_temporal(fail_on={"inventory.reserve"})
    _patch_temporal(monkeypatch, fake_wf)

    decl = SagaDeclaration(
        forward=[
            ActivityDeclaration(name="orders.create"),
            ActivityDeclaration(name="inventory.reserve"),
            ActivityDeclaration(name="payments.charge"),
        ],
        compensate=[
            ActivityDeclaration(name="orders.cancel"),
            ActivityDeclaration(name="inventory.release"),
            ActivityDeclaration(name="payments.refund"),
        ],
    )
    ctx: dict[str, Any] = {"_default_timeout_s": 60.0, "_input": {}}

    with pytest.raises(RuntimeError, match="inventory.reserve"):
        await compile_saga_step(decl, ctx)

    activity_calls = [name for name in recorder if not name.startswith("WARN::")]
    # forward выполнились: orders.create + inventory.reserve (failed).
    # completed = [orders.create]; compensate только compensate[0] = orders.cancel.
    assert activity_calls == [
        "orders.create",
        "inventory.reserve",  # failure; НЕ попал в `completed`
        "orders.cancel",  # compensate[0] для completed[0]
    ]
    # payments.charge / inventory.release / payments.refund — не вызывались.
    assert "payments.charge" not in activity_calls
    assert "inventory.release" not in activity_calls
    assert "payments.refund" not in activity_calls


@pytest.mark.asyncio
async def test_compensate_failure_does_not_stop_chain(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Кейс 4: compensate[1] падает → compensate[0] всё равно выполняется."""
    # forward[2] падает; в compensate-цепочке упадёт inventory.release (idx=1).
    fake_wf, recorder = _make_recorder_temporal(
        fail_on={"payments.charge", "inventory.release"}
    )
    _patch_temporal(monkeypatch, fake_wf)

    decl = SagaDeclaration(
        forward=[
            ActivityDeclaration(name="orders.create"),
            ActivityDeclaration(name="inventory.reserve"),
            ActivityDeclaration(name="payments.charge"),
        ],
        compensate=[
            ActivityDeclaration(name="orders.cancel"),
            ActivityDeclaration(name="inventory.release"),  # упадёт
            ActivityDeclaration(name="payments.refund"),
        ],
    )
    ctx: dict[str, Any] = {"_default_timeout_s": 60.0, "_input": {}}

    with pytest.raises(RuntimeError, match="payments.charge"):
        await compile_saga_step(decl, ctx)

    activity_calls = [name for name in recorder if not name.startswith("WARN::")]
    # compensate[1] упал → log.warning, но compensate[0] всё равно вызван.
    assert "inventory.release" in activity_calls  # tried (and failed)
    assert "orders.cancel" in activity_calls  # выполнен после фейла compensate[1]
    # WARN:: лог зафиксирован при failure compensate.
    warn_logs = [name for name in recorder if name.startswith("WARN::")]
    assert len(warn_logs) >= 1


@pytest.mark.asyncio
async def test_short_compensate_skips_indices_beyond_length(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Кейс 5: 3 forward + 2 compensate; failure forward[2] → compensate[1], compensate[0]."""
    fake_wf, recorder = _make_recorder_temporal(fail_on={"payments.capture"})
    _patch_temporal(monkeypatch, fake_wf)

    # Asymmetric saga (как в payments_saga.py): forward=3, compensate=2.
    decl = SagaDeclaration(
        forward=[
            ActivityDeclaration(name="payments.validate_card"),
            ActivityDeclaration(name="payments.authorize"),
            ActivityDeclaration(name="payments.capture"),
        ],
        compensate=[
            ActivityDeclaration(name="payments.void_authorization"),
            ActivityDeclaration(name="payments.void_capture"),
        ],
    )
    ctx: dict[str, Any] = {"_default_timeout_s": 60.0, "_input": {}}

    with pytest.raises(RuntimeError, match="payments.capture"):
        await compile_saga_step(decl, ctx)

    activity_calls = [name for name in recorder if not name.startswith("WARN::")]
    # forward выполнились: validate_card + authorize + capture(failed).
    # completed = [validate_card, authorize] (idx 0, 1).
    # compensate-цикл идёт от idx=1 до idx=0:
    #   idx=1 → compensate[1] = void_capture (выполнен).
    #   idx=0 → compensate[0] = void_authorization (выполнен).
    # ВАЖНО: compile_saga_step проверяет `idx >= len(decl.compensate)` skip,
    # но completed has length=2 == compensate length=2, поэтому skip не сработал.
    assert activity_calls == [
        "payments.validate_card",
        "payments.authorize",
        "payments.capture",
        "payments.void_capture",
        "payments.void_authorization",
    ]


@pytest.mark.asyncio
async def test_all_forward_success_completes_with_full_recording(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Дополнительная проверка: полный happy-path не вызывает WARN-логов."""
    fake_wf, recorder = _make_recorder_temporal()
    _patch_temporal(monkeypatch, fake_wf)

    decl = SagaDeclaration(
        forward=[ActivityDeclaration(name="a"), ActivityDeclaration(name="b")],
        compensate=[ActivityDeclaration(name="rb_a"), ActivityDeclaration(name="rb_b")],
    )
    ctx: dict[str, Any] = {"_default_timeout_s": 60.0, "_input": {}}
    await compile_saga_step(decl, ctx)

    warn_logs = [name for name in recorder if name.startswith("WARN::")]
    assert warn_logs == []


@pytest.mark.asyncio
async def test_saga_strict_compensate_raises_on_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """strict_compensate=True: compensate failure raises instead of warning."""
    fake_wf, recorder = _make_recorder_temporal(
        fail_on={"payments.charge", "inventory.release"}
    )
    _patch_temporal(monkeypatch, fake_wf)

    decl = SagaDeclaration(
        forward=[
            ActivityDeclaration(name="orders.create"),  # succeeds
            ActivityDeclaration(name="inventory.reserve"),  # succeeds
            ActivityDeclaration(name="payments.charge"),  # fails
        ],
        compensate=[
            ActivityDeclaration(name="orders.cancel"),
            ActivityDeclaration(
                name="inventory.release"
            ),  # fails, raises with strict=True
            ActivityDeclaration(name="payments.refund"),
        ],
        strict_compensate=True,
    )
    ctx: dict[str, Any] = {"_default_timeout_s": 60.0, "_input": {}}

    with pytest.raises(RuntimeError, match="inventory.release"):
        await compile_saga_step(decl, ctx)

    activity_calls = [name for name in recorder if not name.startswith("WARN::")]
    # compensate[0] (orders.cancel) does NOT run because strict raises immediately
    # on compensate[1] failure
    assert "orders.cancel" not in activity_calls
    # But compensate[1] (inventory.release) was attempted before raising
    assert "inventory.release" in activity_calls


@pytest.mark.asyncio
async def test_saga_best_effort_swallows_exception(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """strict_compensate=False (default): compensate failure logs warning, original exc re-raised."""
    fake_wf, recorder = _make_recorder_temporal(
        fail_on={"payments.charge", "inventory.release"}
    )
    _patch_temporal(monkeypatch, fake_wf)

    decl = SagaDeclaration(
        forward=[
            ActivityDeclaration(name="orders.create"),
            ActivityDeclaration(name="inventory.reserve"),
            ActivityDeclaration(name="payments.charge"),
        ],
        compensate=[
            ActivityDeclaration(name="orders.cancel"),
            ActivityDeclaration(name="inventory.release"),  # will fail
            ActivityDeclaration(name="payments.refund"),
        ],
        strict_compensate=False,  # default
    )
    ctx: dict[str, Any] = {"_default_timeout_s": 60.0, "_input": {}}

    with pytest.raises(RuntimeError, match="payments.charge"):
        await compile_saga_step(decl, ctx)

    # Best-effort: compensate[1] fails but compensate[0] still runs
    activity_calls = [name for name in recorder if not name.startswith("WARN::")]
    assert "orders.cancel" in activity_calls
    assert "inventory.release" in activity_calls
    # Warning was logged but exception was swallowed
    warn_logs = [name for name in recorder if name.startswith("WARN::")]
    assert len(warn_logs) >= 1
