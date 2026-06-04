"""Unit-тесты ``SagaLRAProcessor``.

Покрывают:

* fallback к in-memory saga при недоступности БД;
* успешное выполнение с checkpoint'ами и final state ``completed``;
* resume с ``step_index + 1``;
* ошибка на шаге → compensating_actions → компенсация → ``rolled_back``;
* ошибка компенсации → state ``compensating``;
* ``to_spec`` сериализация.
"""

# ruff: noqa: S101

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.backend.dsl.engine.exchange import Exchange, ExchangeStatus, Message
from src.backend.dsl.engine.processors.base import BaseProcessor
from src.backend.dsl.engine.processors.control_flow import SagaStep
from src.backend.dsl.engine.processors.saga_lra import SagaLRAProcessor


class _FakeProcessor(BaseProcessor):
    """Fake processor для тестов с опц. fail / raise_exc."""

    def __init__(
        self, name: str, *, fail: bool = False, raise_exc: bool = False
    ) -> None:
        super().__init__(name=name)
        self.fail = fail
        self.raise_exc = raise_exc
        self.called = False

    async def process(self, exchange: Exchange[Any], context: Any) -> None:
        self.called = True
        if self.raise_exc:
            raise RuntimeError(f"raise:{self.name}")
        if self.fail:
            exchange.fail(f"fail:{self.name}")

    def to_spec(self) -> dict[str, Any] | None:
        return {self.name: {}}


def _ex(body: Any = None, headers: dict[str, Any] | None = None) -> Exchange[Any]:
    return Exchange(in_message=Message(body=body or {}, headers=headers or {}))


@pytest.fixture
def steps() -> list[SagaStep]:
    return [
        SagaStep(forward=_FakeProcessor("f0"), compensate=_FakeProcessor("c0")),
        SagaStep(forward=_FakeProcessor("f1"), compensate=_FakeProcessor("c1")),
    ]


@pytest.mark.asyncio
async def test_fallback_in_memory_when_db_unavailable(steps: list[SagaStep]) -> None:
    proc = SagaLRAProcessor(steps, workflow_id="wf1", run_id="r1")
    with patch.object(proc, "_get_repo", new=AsyncMock(return_value=None)):
        ex = _ex()
        ctx = AsyncMock()
        await proc.process(ex, ctx)

    assert ex.status != ExchangeStatus.failed
    assert ex.get_property("saga_completed") is True
    assert steps[0].forward.called  # type: ignore[union-attr]
    assert steps[1].forward.called  # type: ignore[union-attr]


@pytest.mark.asyncio
async def test_success_with_db_creates_checkpoints_and_completed(
    steps: list[SagaStep],
) -> None:
    proc = SagaLRAProcessor(steps, workflow_id="wf1", run_id="r1")

    mock_state = MagicMock()
    mock_state.step_index = -1

    mock_repo = MagicMock()
    mock_repo.load = AsyncMock(return_value=mock_state)
    mock_repo.save = AsyncMock(return_value=mock_state)

    with patch.object(proc, "_get_repo", new=AsyncMock(return_value=mock_repo)):
        ex = _ex()
        ctx = AsyncMock()
        await proc.process(ex, ctx)

    assert ex.status != ExchangeStatus.failed
    assert ex.get_property("saga_completed") is True
    assert mock_repo.save.call_count == 3  # checkpoint0, checkpoint1, completed
    assert mock_repo.save.call_args_list[-1].kwargs["state"] == "completed"


@pytest.mark.asyncio
async def test_resume_from_step_index(steps: list[SagaStep]) -> None:
    proc = SagaLRAProcessor(steps, workflow_id="wf1", run_id="r1")

    mock_state = MagicMock()
    mock_state.step_index = 0  # step 0 уже выполнен

    mock_repo = MagicMock()
    mock_repo.load = AsyncMock(return_value=mock_state)
    mock_repo.save = AsyncMock(return_value=mock_state)

    with patch.object(proc, "_get_repo", new=AsyncMock(return_value=mock_repo)):
        ex = _ex()
        ctx = AsyncMock()
        await proc.process(ex, ctx)

    assert ex.status != ExchangeStatus.failed
    assert not steps[0].forward.called  # type: ignore[union-attr]
    assert steps[1].forward.called  # type: ignore[union-attr]
    assert mock_repo.save.call_count == 2  # checkpoint1, completed


@pytest.mark.asyncio
async def test_failure_triggers_compensation_and_rolled_back() -> None:
    steps = [
        SagaStep(forward=_FakeProcessor("f0"), compensate=_FakeProcessor("c0")),
        SagaStep(
            forward=_FakeProcessor("f1", fail=True), compensate=_FakeProcessor("c1")
        ),
    ]
    proc = SagaLRAProcessor(steps, workflow_id="wf1", run_id="r1")

    mock_state = MagicMock()
    mock_state.step_index = -1

    mock_repo = MagicMock()
    mock_repo.load = AsyncMock(return_value=mock_state)
    mock_repo.save = AsyncMock(return_value=mock_state)

    with patch.object(proc, "_get_repo", new=AsyncMock(return_value=mock_repo)):
        ex = _ex()
        ctx = AsyncMock()
        await proc.process(ex, ctx)

    assert ex.status == ExchangeStatus.failed
    assert ex.get_property("saga_failed_step") == 1

    # c0 вызвана, c1 — нет (текущий шаг не компенсируется)
    assert steps[0].compensate.called  # type: ignore[union-attr]
    assert not steps[1].compensate.called  # type: ignore[union-attr]

    # Проверяем compensating_actions
    comp_calls = [
        c
        for c in mock_repo.save.call_args_list
        if c.kwargs.get("state") == "compensating"
    ]
    assert len(comp_calls) == 1
    assert comp_calls[0].kwargs["compensating_actions"] == [
        {"step_index": 0, "forward_name": "f0", "compensate_name": "c0"}
    ]

    # Финальное состояние — rolled_back
    final_call = mock_repo.save.call_args_list[-1]
    assert final_call.kwargs["state"] == "rolled_back"


@pytest.mark.asyncio
async def test_failure_when_compensation_fails_state_is_compensating() -> None:
    steps = [
        SagaStep(
            forward=_FakeProcessor("f0"),
            compensate=_FakeProcessor("c0", raise_exc=True),
        ),
        SagaStep(
            forward=_FakeProcessor("f1", fail=True), compensate=_FakeProcessor("c1")
        ),
    ]
    proc = SagaLRAProcessor(steps, workflow_id="wf1", run_id="r1")

    mock_state = MagicMock()
    mock_state.step_index = -1

    mock_repo = MagicMock()
    mock_repo.load = AsyncMock(return_value=mock_state)
    mock_repo.save = AsyncMock(return_value=mock_state)

    with patch.object(proc, "_get_repo", new=AsyncMock(return_value=mock_repo)):
        ex = _ex()
        ctx = AsyncMock()
        await proc.process(ex, ctx)

    assert ex.status == ExchangeStatus.failed
    final_call = mock_repo.save.call_args_list[-1]
    assert final_call.kwargs["state"] == "compensating"


@pytest.mark.asyncio
async def test_db_load_failure_falls_back_to_in_memory(steps: list[SagaStep]) -> None:
    proc = SagaLRAProcessor(steps, workflow_id="wf1", run_id="r1")

    mock_repo = MagicMock()
    mock_repo.load = AsyncMock(side_effect=RuntimeError("DB down"))

    with patch.object(proc, "_get_repo", new=AsyncMock(return_value=mock_repo)):
        ex = _ex()
        ctx = AsyncMock()
        await proc.process(ex, ctx)

    assert ex.status != ExchangeStatus.failed
    assert ex.get_property("saga_completed") is True


@pytest.mark.asyncio
async def test_to_spec_roundtrip() -> None:
    steps = [SagaStep(forward=_FakeProcessor("f0"), compensate=_FakeProcessor("c0"))]
    proc = SagaLRAProcessor(steps, workflow_id="wf1", run_id="r1")
    spec = proc.to_spec()
    assert spec is not None
    assert "saga_lra" in spec
    assert spec["saga_lra"]["workflow_id"] == "wf1"
    assert spec["saga_lra"]["run_id"] == "r1"
    assert len(spec["saga_lra"]["steps"]) == 1


@pytest.mark.asyncio
async def test_to_spec_returns_none_when_not_serializable() -> None:
    steps = [SagaStep(forward=_FakeProcessor("f0"), compensate=None)]

    # Если forward.to_spec() вернёт None, to_spec должен вернуть None
    class _NoSpecProcessor(BaseProcessor):
        async def process(self, exchange: Exchange[Any], context: Any) -> None:
            pass

    steps = [SagaStep(forward=_NoSpecProcessor("nospec"), compensate=None)]
    proc = SagaLRAProcessor(steps)
    spec = proc.to_spec()
    assert spec is None
