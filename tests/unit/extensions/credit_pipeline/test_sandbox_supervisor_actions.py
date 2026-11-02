"""ADR-0409: sandbox-исполнитель и supervisor-диспетчеризация расширения.

Дефект (до фикса)
-----------------
``code_interpreter_loop.workflow.yaml`` подменял «e2b-sandbox»-шаг
LLM-вызовом ``ai.run_agent`` (код не исполнялся), а
``multi_agent_supervisor.workflow.yaml`` — LLM-вызовом «supervisor»,
который ничего не диспетчеризировал. Отдельных risk/compliance-агентов
в расширении нет.

Ожидание
--------
* ``execute_code`` исполняет код в core-sandbox'е (``CodeSandbox``) и
  fail-closed отказывает, если sandbox недоступен (без ``subprocess``);
* ``evaluate_result`` даёт вердикт по результату исполнения;
* ``supervise`` раздаёт заявку **реальным** агентам расширения через
  core-супервизор (не stub-агенты ядра);
* plugin регистрирует оба новых action'а.
"""

from __future__ import annotations

from typing import Any

import pytest

from extensions.credit_pipeline.sandbox import evaluate_result, execute_code
from extensions.credit_pipeline.supervisor import supervise
from src.backend.core import svcs_registry
from src.backend.core.ai.sandbox import CodeSandbox, NoOpSandbox, SandboxResult

pytestmark = pytest.mark.unit


class _StubSandbox:
    """Тестовый sandbox: возвращает заранее заданный результат."""

    def __init__(self, result: SandboxResult) -> None:
        self._result = result
        self.calls: list[tuple[str, float]] = []

    async def run(self, code: str, *, timeout_s: float = 30.0, **_: Any) -> SandboxResult:
        """Запомнить вызов и вернуть подготовленный результат."""
        self.calls.append((code, timeout_s))
        return self._result


@pytest.fixture
def stub_sandbox(monkeypatch: pytest.MonkeyPatch) -> _StubSandbox:
    """Регистрирует тестовый ``CodeSandbox`` в DI-контейнере ядра.

    Регистрация откатывается monkeypatch'ем — глобальное состояние
    контейнера не должно «протекать» в следующие тесты.
    """
    sandbox = _StubSandbox(
        SandboxResult(
            stdout="42",
            stderr="",
            exit_code=0,
            artifacts={"report.csv": b"a,b"},
        )
    )
    _register_sandbox(monkeypatch, lambda: sandbox)
    return sandbox


def _register_sandbox(
    monkeypatch: pytest.MonkeyPatch, factory: Any
) -> None:
    """Зарегистрировать sandbox-фабрику с авто-откатом.

    Args:
        monkeypatch: Фикстура pytest (откатывает изменения после теста).
        factory: Фабрика, возвращающая экземпляр sandbox'а.

    """
    monkeypatch.setitem(svcs_registry._factories, CodeSandbox, factory)
    monkeypatch.delitem(svcs_registry._singletons, CodeSandbox, raising=False)


def _unregister_sandbox(monkeypatch: pytest.MonkeyPatch) -> None:
    """Убрать sandbox из DI-контейнера (с авто-откатом).

    Args:
        monkeypatch: Фикстура pytest (откатывает изменения после теста).

    """
    monkeypatch.delitem(svcs_registry._factories, CodeSandbox, raising=False)
    monkeypatch.delitem(svcs_registry._singletons, CodeSandbox, raising=False)


# ──────────────────────────────────────────────────────────────────────
# execute_code
# ──────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_execute_code_runs_code_in_core_sandbox(
    stub_sandbox: _StubSandbox,
) -> None:
    """Код исполняется в core-sandbox'е, наружу — сериализуемый результат."""
    result = await execute_code({"code": "print(42)", "timeout_s": 15.0})

    assert stub_sandbox.calls == [("print(42)", 15.0)]
    assert result["stdout"] == "42"
    assert result["exit_code"] == 0
    # Байты артефактов не сериализуются в Temporal-payload — только имена.
    assert result["artifacts"] == ["report.csv"]


@pytest.mark.asyncio
async def test_execute_code_rejects_empty_code(stub_sandbox: _StubSandbox) -> None:
    """Без кода — понятная ошибка, sandbox не вызывается."""
    with pytest.raises(ValueError, match="code"):
        await execute_code({})

    assert stub_sandbox.calls == []


@pytest.mark.asyncio
async def test_execute_code_fails_closed_without_sandbox_service(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Sandbox не зарегистрирован → RuntimeError, а не локальный запуск кода."""
    _unregister_sandbox(monkeypatch)

    with pytest.raises(RuntimeError, match="CodeSandbox"):
        await execute_code({"code": "print(1)"})


@pytest.mark.asyncio
async def test_execute_code_propagates_noop_sandbox_refusal(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """NoOpSandbox (нет E2B) — явный отказ, код НЕ исполняется."""
    _register_sandbox(monkeypatch, NoOpSandbox)

    with pytest.raises(RuntimeError):
        await execute_code({"code": "print(1)"})


# ──────────────────────────────────────────────────────────────────────
# evaluate_result
# ──────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_evaluate_result_done_on_success() -> None:
    """exit_code=0 и непустой stdout → done=True."""
    result = await evaluate_result({"exit_code": 0, "stdout": "42", "stderr": ""})

    assert result["done"] is True
    assert result["exit_code"] == 0


@pytest.mark.asyncio
async def test_evaluate_result_not_done_on_error() -> None:
    """Ошибка исполнения → done=False (нужна итерация)."""
    result = await evaluate_result({"exit_code": 1, "stdout": "", "stderr": "boom"})

    assert result["done"] is False
    assert "итерация" in result["summary"]


# ──────────────────────────────────────────────────────────────────────
# supervise
# ──────────────────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_supervise_uses_real_extension_agents() -> None:
    """Супервизор раздаёт заявку реальным агентам расширения.

    Проверяем, что в выводе — результат настоящего ``scoring_agent``
    (``stub``-маркера нет), а не заглушка ядра.
    """
    result = await supervise(
        {
            "applicant_id": 1,
            "amount": 100_000,
            "duration_months": 12,
            "monthly_income": 200_000,
            "purpose": "car",
        }
    )

    assert result["supervisor"] == "credit_orchestrator"
    assert "scoring_agent" in result["agents_invoked"]
    assert result["scoring"].get("stub") is False
    assert result["credit_score"] == result["scoring"]["credit_score"]
    assert result["risk_class"] in ("LOW", "MEDIUM", "HIGH")
    # Разбор документов — тоже реальный агент расширения.
    assert result["document"].get("agent") == "document_parser_agent"


@pytest.mark.asyncio
async def test_supervise_fails_closed_without_agents_output(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Супервизор не вызвал ни одного агента → ошибка (fail-closed)."""
    import src.backend.core.ai.multi_agent as core_multi_agent

    class _DeadSupervisor:
        """Супервизор, который ничего не вызвал."""

        def __init__(self, **_kwargs: Any) -> None:
            pass

        async def run(self, *, prompt: str, payload: dict[str, Any]) -> dict[str, Any]:
            return {
                "supervisor": "credit_orchestrator",
                "agents_invoked": [],
                "outputs": [],
                "final_response": "",
                "error": "feature_flag.multi_agent_supervisor_enabled выключен",
            }

    monkeypatch.setattr(core_multi_agent, "MultiAgentSupervisor", _DeadSupervisor)

    with pytest.raises(RuntimeError, match="недоступен"):
        await supervise({"applicant_id": 1})


@pytest.mark.asyncio
async def test_plugin_registers_sandbox_and_supervisor_actions() -> None:
    """Plugin регистрирует 5 actions, включая новые (ADR-0409)."""
    from extensions.credit_pipeline.plugin import CreditPipelinePlugin

    class _RecordingRegistry:
        def __init__(self) -> None:
            self.registered: dict[str, Any] = {}

        def register(self, action_id: str, handler: Any, *, spec: Any = None) -> None:
            self.registered[action_id] = handler

    registry = _RecordingRegistry()
    await CreditPipelinePlugin().on_register_actions(registry)  # type: ignore[arg-type]

    assert set(registry.registered) == {
        "credit_pipeline.score",
        "credit_pipeline.parse",
        "credit_pipeline.decide",
        "credit_pipeline.execute_code",
        "credit_pipeline.supervise",
    }


@pytest.mark.asyncio
async def test_execute_code_action_accepts_flat_payload() -> None:
    """Action-обёртка принимает плоский payload (контракт DSL-действия)."""
    from extensions.credit_pipeline.plugin import CreditPipelinePlugin

    class _RecordingRegistry:
        def __init__(self) -> None:
            self.registered: dict[str, Any] = {}

        def register(self, action_id: str, handler: Any, *, spec: Any = None) -> None:
            self.registered[action_id] = handler

    registry = _RecordingRegistry()
    await CreditPipelinePlugin().on_register_actions(registry)  # type: ignore[arg-type]

    handler = registry.registered["credit_pipeline.execute_code"]
    with pytest.raises(ValueError, match="code"):
        # Плоский payload без 'code' → понятная ошибка, а не TypeError.
        await handler(timeout_s=10)
