"""Тесты :mod:`dsl.workflow.compiler.step_compilers`.

Каждый компилятор (activity / saga / signal_wait / sleep / sensor)
проверяется на корректную интеграцию с ``temporalio.workflow.*``.
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

from src.backend.dsl.workflow.compiler.step_compilers import (
    _build_retry_policy,
    compile_activity_step,
    compile_saga_step,
    compile_sensor_step,
    compile_signal_wait_step,
    compile_sleep_step,
    dispatch_step_compile,
)
from src.backend.dsl.workflow.spec import (
    ActivityDeclaration,
    RetryPolicy,
    SagaDeclaration,
    SensorDeclaration,
    SignalWaitDeclaration,
    SleepDeclaration,
)


def _make_fake_temporal(
    *, execute_activity_return: Any = None, wait_condition_blocks: bool = False
) -> tuple[SimpleNamespace, list[Any]]:
    """Сконструировать fake-модуль ``temporalio.workflow`` с записью вызовов."""
    recorder: list[Any] = []

    async def fake_execute_activity(
        name: str, payload: Any = None, **kwargs: Any
    ) -> Any:
        recorder.append(
            {
                "kind": "execute_activity",
                "name": name,
                "payload": payload,
                "kwargs": kwargs,
            }
        )
        return execute_activity_return

    async def fake_sleep(duration: timedelta) -> None:
        recorder.append({"kind": "sleep", "duration": duration})

    async def fake_wait_condition(
        predicate: Any, timeout: timedelta | None = None
    ) -> None:
        recorder.append({"kind": "wait_condition", "timeout": timeout})
        if wait_condition_blocks and not predicate():
            raise TimeoutError("wait_condition_blocks=True simulates timeout")

    fake_workflow_module = SimpleNamespace(
        execute_activity=fake_execute_activity,
        sleep=fake_sleep,
        wait_condition=fake_wait_condition,
        logger=SimpleNamespace(
            warning=lambda *a, **kw: recorder.append({"kind": "log_warn", "args": a})
        ),
    )
    return fake_workflow_module, recorder


def _make_fake_common() -> SimpleNamespace:
    class FakeRetryPolicy:
        def __init__(self, **kwargs: Any) -> None:
            self.kwargs = kwargs

    return SimpleNamespace(RetryPolicy=FakeRetryPolicy)


@pytest.fixture
def temporal_mock(monkeypatch: pytest.MonkeyPatch) -> tuple[SimpleNamespace, list[Any]]:
    """Mock ``temporalio.workflow`` + ``temporalio.common``."""
    fake_wf, recorder = _make_fake_temporal()
    fake_common = _make_fake_common()
    fake_temporalio = SimpleNamespace(workflow=fake_wf, common=fake_common)
    monkeypatch.setitem(sys.modules, "temporalio", fake_temporalio)
    monkeypatch.setitem(sys.modules, "temporalio.workflow", fake_wf)
    monkeypatch.setitem(sys.modules, "temporalio.common", fake_common)
    return fake_wf, recorder


# ---------- compile_activity_step ----------


@pytest.mark.asyncio
async def test_activity_step_executes_with_default_timeout(
    temporal_mock: tuple[SimpleNamespace, list[Any]],
) -> None:
    _, recorder = temporal_mock
    decl = ActivityDeclaration(name="orders.create")
    ctx = {"_default_timeout_s": 60.0, "_input": {"a": 1}, "_outputs": {}}
    await compile_activity_step(decl, ctx)
    assert len(recorder) == 1
    call = recorder[0]
    assert call["name"] == "orders.create"
    assert call["kwargs"]["start_to_close_timeout"] == timedelta(seconds=60.0)
    # Default-input в payload.
    assert call["payload"]["_workflow_input"] == {"a": 1}


@pytest.mark.asyncio
async def test_activity_step_uses_explicit_timeout(
    temporal_mock: tuple[SimpleNamespace, list[Any]],
) -> None:
    _, recorder = temporal_mock
    decl = ActivityDeclaration(name="orders.create", timeout_s=15.0)
    ctx = {"_default_timeout_s": 60.0, "_input": {}}
    await compile_activity_step(decl, ctx)
    assert recorder[0]["kwargs"]["start_to_close_timeout"] == timedelta(seconds=15.0)


@pytest.mark.asyncio
async def test_activity_step_writes_output_key(monkeypatch: pytest.MonkeyPatch) -> None:
    fake_wf, recorder = _make_fake_temporal(execute_activity_return={"id": 42})
    monkeypatch.setitem(
        sys.modules,
        "temporalio",
        SimpleNamespace(workflow=fake_wf, common=_make_fake_common()),
    )
    monkeypatch.setitem(sys.modules, "temporalio.workflow", fake_wf)
    monkeypatch.setitem(sys.modules, "temporalio.common", _make_fake_common())

    decl = ActivityDeclaration(name="orders.create", output_key="order")
    ctx: dict[str, Any] = {"_default_timeout_s": 30.0, "_input": {}}
    await compile_activity_step(decl, ctx)
    assert ctx["_outputs"] == {"order": {"id": 42}}


@pytest.mark.asyncio
async def test_activity_step_applies_retry_policy(
    temporal_mock: tuple[SimpleNamespace, list[Any]],
) -> None:
    _, recorder = temporal_mock
    policy = RetryPolicy(
        max_attempts=5, initial_interval_s=2.0, backoff_coefficient=3.0
    )
    decl = ActivityDeclaration(name="x", retry_policy=policy)
    ctx = {"_default_timeout_s": 60.0, "_input": {}}
    await compile_activity_step(decl, ctx)
    rp = recorder[0]["kwargs"]["retry_policy"]
    assert rp is not None
    assert rp.kwargs["maximum_attempts"] == 5
    assert rp.kwargs["initial_interval"] == timedelta(seconds=2.0)
    assert rp.kwargs["backoff_coefficient"] == 3.0


# ---------- compile_saga_step ----------


@pytest.mark.asyncio
async def test_saga_step_all_forward_success_no_compensate(
    temporal_mock: tuple[SimpleNamespace, list[Any]],
) -> None:
    _, recorder = temporal_mock
    decl = SagaDeclaration(
        forward=[
            ActivityDeclaration(name="orders.create"),
            ActivityDeclaration(name="payment.charge"),
        ],
        compensate=[
            ActivityDeclaration(name="orders.cancel"),
            ActivityDeclaration(name="payment.refund"),
        ],
    )
    ctx = {"_default_timeout_s": 60.0, "_input": {}}
    await compile_saga_step(decl, ctx)
    activity_calls = [r["name"] for r in recorder if r["kind"] == "execute_activity"]
    # Только forward выполнились.
    assert activity_calls == ["orders.create", "payment.charge"]


# ---------- compile_signal_wait_step ----------


@pytest.mark.asyncio
async def test_signal_wait_returns_payload_when_signal_present(
    temporal_mock: tuple[SimpleNamespace, list[Any]],
) -> None:
    _, recorder = temporal_mock
    decl = SignalWaitDeclaration(signal_name="approve", output_key="decision")
    ctx: dict[str, Any] = {"_signals": {"approve": {"by": "manager"}}, "_outputs": {}}
    payload = await compile_signal_wait_step(decl, ctx)
    assert payload == {"by": "manager"}
    assert ctx["_outputs"]["decision"] == {"by": "manager"}
    # signal удаляется после потребления.
    assert "approve" not in ctx["_signals"]


@pytest.mark.asyncio
async def test_signal_wait_with_timeout_records_call(
    temporal_mock: tuple[SimpleNamespace, list[Any]],
) -> None:
    fake_wf, recorder = temporal_mock
    decl = SignalWaitDeclaration(signal_name="approve", timeout_s=120.0)
    ctx: dict[str, Any] = {"_signals": {"approve": {"x": 1}}}
    await compile_signal_wait_step(decl, ctx)
    wait_calls = [r for r in recorder if r["kind"] == "wait_condition"]
    assert len(wait_calls) == 1
    assert wait_calls[0]["timeout"] == timedelta(seconds=120.0)


# ---------- compile_sleep_step ----------


@pytest.mark.asyncio
async def test_sleep_step_delegates_to_workflow_sleep(
    temporal_mock: tuple[SimpleNamespace, list[Any]],
) -> None:
    _, recorder = temporal_mock
    decl = SleepDeclaration(duration_s=2.5)
    await compile_sleep_step(decl, {})
    assert recorder == [{"kind": "sleep", "duration": timedelta(seconds=2.5)}]


# ---------- compile_sensor_step ----------


@pytest.mark.asyncio
async def test_sensor_step_returns_truthy_first_iteration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Sensor возвращает truthy на 1й итерации → конец."""
    fake_wf, recorder = _make_fake_temporal(execute_activity_return=True)
    monkeypatch.setitem(
        sys.modules,
        "temporalio",
        SimpleNamespace(workflow=fake_wf, common=_make_fake_common()),
    )
    monkeypatch.setitem(sys.modules, "temporalio.workflow", fake_wf)
    monkeypatch.setitem(sys.modules, "temporalio.common", _make_fake_common())

    decl = SensorDeclaration(predicate="src.x:check", poll_interval_s=10.0)
    ctx = {"_default_timeout_s": 30.0}
    result = await compile_sensor_step(decl, ctx)
    assert result is True
    activity_calls = [r for r in recorder if r["kind"] == "execute_activity"]
    assert len(activity_calls) == 1


@pytest.mark.asyncio
async def test_sensor_step_timeout_raises(monkeypatch: pytest.MonkeyPatch) -> None:
    """Sensor падает в TimeoutError если predicate не truthy + истёк timeout."""
    fake_wf, recorder = _make_fake_temporal(execute_activity_return=False)
    monkeypatch.setitem(
        sys.modules,
        "temporalio",
        SimpleNamespace(workflow=fake_wf, common=_make_fake_common()),
    )
    monkeypatch.setitem(sys.modules, "temporalio.workflow", fake_wf)
    monkeypatch.setitem(sys.modules, "temporalio.common", _make_fake_common())

    decl = SensorDeclaration(
        predicate="src.x:check", poll_interval_s=1.0, timeout_s=2.0
    )
    ctx = {"_default_timeout_s": 30.0}
    with pytest.raises(TimeoutError):
        await compile_sensor_step(decl, ctx)


# ---------- dispatch_step_compile ----------


@pytest.mark.asyncio
async def test_dispatch_routes_each_step_type(
    temporal_mock: tuple[SimpleNamespace, list[Any]],
) -> None:
    _, recorder = temporal_mock
    ctx: dict[str, Any] = {
        "_default_timeout_s": 30.0,
        "_input": {},
        "_outputs": {},
        "_signals": {"approve": {}},
    }
    # Dispatch для всех 5 типов.
    await dispatch_step_compile(ActivityDeclaration(name="a"), ctx)
    await dispatch_step_compile(SleepDeclaration(duration_s=1.0), ctx)
    await dispatch_step_compile(SignalWaitDeclaration(signal_name="approve"), ctx)
    kinds = [r["kind"] for r in recorder]
    assert "execute_activity" in kinds
    assert "sleep" in kinds
    assert "wait_condition" in kinds


@pytest.mark.asyncio
async def test_dispatch_unknown_step_raises_typeerror() -> None:
    class FakeStep:
        pass

    with pytest.raises(TypeError, match="No step compiler registered"):
        await dispatch_step_compile(FakeStep(), {})  # type: ignore[arg-type]


# ---------- _build_retry_policy ----------


def test_build_retry_policy_returns_none_when_both_none(
    temporal_mock: tuple[SimpleNamespace, list[Any]],
) -> None:
    assert _build_retry_policy(None, None) is None


def test_build_retry_policy_uses_decl_over_default(
    temporal_mock: tuple[SimpleNamespace, list[Any]],
) -> None:
    decl_policy = RetryPolicy(max_attempts=7)
    default_policy = RetryPolicy(max_attempts=2)
    rp = _build_retry_policy(decl_policy, default_policy)
    assert rp.kwargs["maximum_attempts"] == 7


def test_build_retry_policy_falls_back_to_default(
    temporal_mock: tuple[SimpleNamespace, list[Any]],
) -> None:
    default_policy = RetryPolicy(max_attempts=4)
    rp = _build_retry_policy(None, default_policy)
    assert rp.kwargs["maximum_attempts"] == 4


def test_build_retry_policy_includes_max_interval_and_non_retryable(
    temporal_mock: tuple[SimpleNamespace, list[Any]],
) -> None:
    policy = RetryPolicy(
        max_attempts=3,
        maximum_interval_s=10.0,
        non_retryable_errors=("ValidationError", "AuthError"),
    )
    rp = _build_retry_policy(policy, None)
    assert rp.kwargs["maximum_interval"] == timedelta(seconds=10.0)
    assert rp.kwargs["non_retryable_error_types"] == ["ValidationError", "AuthError"]


# ---------- compile_agent_invoke_step ----------


@pytest.mark.asyncio
async def test_agent_invoke_step_stateless_basic(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Test stateless agent_invoke calls AIGateway with correct input."""
    from types import SimpleNamespace

    fake_wf, recorder = _make_fake_temporal()
    monkeypatch.setitem(
        sys.modules,
        "temporalio",
        SimpleNamespace(workflow=fake_wf, common=_make_fake_common()),
    )
    monkeypatch.setitem(sys.modules, "temporalio.workflow", fake_wf)
    monkeypatch.setitem(sys.modules, "temporalio.common", _make_fake_common())

    # Mock AIGateway
    class MockAIResponse:
        content = "Credit approved"

    class MockAIGateway:
        async def invoke(self, request, timeout=None):
            return MockAIResponse()

    monkeypatch.setattr(
        "src.backend.core.ai.gateway.AIGateway", lambda: MockAIGateway()
    )

    from src.backend.dsl.workflow.compiler.step_compilers import (
        compile_agent_invoke_step,
    )
    from src.backend.dsl.workflow.spec import AgentInvokeDeclaration

    decl = AgentInvokeDeclaration(agent_id="credit_advisor", durable=False)
    ctx: dict[str, Any] = {
        "_default_timeout_s": 60.0,
        "_input": {"user_input": "approve my loan"},
    }
    result = await compile_agent_invoke_step(decl, ctx)
    assert result.content == "Credit approved"


@pytest.mark.asyncio
async def test_agent_invoke_step_durable_falls_back_to_stateless(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Test durable agent_invoke falls back to stateless when checkpointer unavailable."""
    from types import SimpleNamespace

    fake_wf, recorder = _make_fake_temporal()
    monkeypatch.setitem(
        sys.modules,
        "temporalio",
        SimpleNamespace(workflow=fake_wf, common=_make_fake_common()),
    )
    monkeypatch.setitem(sys.modules, "temporalio.workflow", fake_wf)
    monkeypatch.setitem(sys.modules, "temporalio.common", _make_fake_common())

    class MockAIResponse:
        content = "Approved"

    class MockAIGateway:
        async def invoke(self, request, timeout=None):
            return MockAIResponse()

    monkeypatch.setattr(
        "src.backend.core.ai.gateway.AIGateway", lambda: MockAIGateway()
    )
    # Make LangGraph checkpointer return None (unavailable)
    monkeypatch.setattr(
        "src.backend.services.ai.agents.langgraph_postgres_saver.get_langgraph_postgres_saver",
        lambda: None,
    )

    from src.backend.dsl.workflow.compiler.step_compilers import (
        compile_agent_invoke_step,
    )
    from src.backend.dsl.workflow.spec import AgentInvokeDeclaration

    decl = AgentInvokeDeclaration(agent_id="credit_advisor", durable=True)
    ctx: dict[str, Any] = {"_default_timeout_s": 60.0, "_input": {"text": "test"}}
    result = await compile_agent_invoke_step(decl, ctx)
    assert result.content == "Approved"


@pytest.mark.asyncio
async def test_agent_invoke_writes_output_key(monkeypatch: pytest.MonkeyPatch) -> None:
    """Test agent_invoke writes result to ctx._outputs."""
    from types import SimpleNamespace

    fake_wf, recorder = _make_fake_temporal()
    monkeypatch.setitem(
        sys.modules,
        "temporalio",
        SimpleNamespace(workflow=fake_wf, common=_make_fake_common()),
    )
    monkeypatch.setitem(sys.modules, "temporalio.workflow", fake_wf)
    monkeypatch.setitem(sys.modules, "temporalio.common", _make_fake_common())

    class MockAIResponse:
        content = "Result content"

    class MockAIGateway:
        async def invoke(self, request, timeout=None):
            return MockAIResponse()

    monkeypatch.setattr(
        "src.backend.core.ai.gateway.AIGateway", lambda: MockAIGateway()
    )

    from src.backend.dsl.workflow.compiler.step_compilers import (
        compile_agent_invoke_step,
    )
    from src.backend.dsl.workflow.spec import AgentInvokeDeclaration

    decl = AgentInvokeDeclaration(agent_id="credit_advisor", output_key="agent_result")
    ctx: dict[str, Any] = {
        "_default_timeout_s": 60.0,
        "_input": {"query": "hello"},
        "_outputs": {},
    }
    await compile_agent_invoke_step(decl, ctx)
    assert "agent_result" in ctx["_outputs"]


@pytest.mark.asyncio
async def test_agent_invoke_resolves_dot_path_input(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Test agent_invoke resolves ${body.query} style input_context."""
    from types import SimpleNamespace

    fake_wf, recorder = _make_fake_temporal()
    monkeypatch.setitem(
        sys.modules,
        "temporalio",
        SimpleNamespace(workflow=fake_wf, common=_make_fake_common()),
    )
    monkeypatch.setitem(sys.modules, "temporalio.workflow", fake_wf)
    monkeypatch.setitem(sys.modules, "temporalio.common", _make_fake_common())

    captured_request = None

    class MockAIResponse:
        content = "Done"

    class MockAIGateway:
        async def invoke(self, request, timeout=None):
            nonlocal captured_request
            captured_request = request
            return MockAIResponse()

    monkeypatch.setattr(
        "src.backend.core.ai.gateway.AIGateway", lambda: MockAIGateway()
    )

    from src.backend.dsl.workflow.compiler.step_compilers import (
        compile_agent_invoke_step,
    )
    from src.backend.dsl.workflow.spec import AgentInvokeDeclaration

    decl = AgentInvokeDeclaration(
        agent_id="credit_advisor", input_context="${body.user_query}", durable=False
    )
    ctx: dict[str, Any] = {
        "_default_timeout_s": 60.0,
        "_input": {"body": {"user_query": "my credit request"}},
    }
    await compile_agent_invoke_step(decl, ctx)
    assert captured_request is not None
    assert "my credit request" in str(captured_request.prompt_inline)
