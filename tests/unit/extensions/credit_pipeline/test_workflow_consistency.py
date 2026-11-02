"""ADR-0409: консистентность workflow-деклараций расширения credit_pipeline.

Что проверяется (сверх build-time резолва из
``test_workflow_activities_resolve.py``):

1. **Каждый** шаг ссылается на существующую цель: зарегистрированный
   action ядра либо module-level callable расширения;
2. module:fn-цели принимают РОВНО один позиционный аргумент — payload
   (``call_function`` вызывает ``fn(payload)``);
3. args module:fn-шага — это сам payload (плоский контракт): вложенные
   обёртки ``body``/``responses``/``payload`` до цели не доходят
   (был источник «тихих» KeyError/пустых нормализаций);
4. ``decision_agent`` получает реальный вывод ``scoring_agent``
   (иначе credit_score=0 → кредит отклоняется всегда);
5. вымышленные activity-имена (risk_agent, e2b-sandbox и пр.) не
   возвращаются в декларации.
"""

from __future__ import annotations

import importlib
import inspect
from pathlib import Path

import pytest

from src.backend.dsl.commands.action_registry import action_handler_registry
from src.backend.dsl.commands.setup import register_action_handlers
from src.backend.dsl.portal import load_workflow_from_yaml
from src.backend.dsl.workflow.spec import is_call_function_ref

pytestmark = pytest.mark.unit

REPO_ROOT = Path(__file__).resolve().parents[4]
EXTENSIONS_DIR = REPO_ROOT / "extensions"

#: Ключи-обёртки, которые «съедают» payload module:fn-шага.
_PAYLOAD_WRAPPER_KEYS = frozenset({"body", "responses", "payload"})

#: Вымышленные activity-имена (ADR-0403/ADR-0409) — не должны вернуться.
_FICTIONAL_TARGETS = frozenset(
    {
        "collect_loan_inputs",
        "compliance_agent",
        "evaluate_results",
        "execute_code_sandboxed",
        "fetch_credit_data",
        "final_decision",
        "format_final_report",
        "fund_account",
        "llm_credit_decision",
        "llm_propose_code",
        "rag_query_legal_policies",
        "receive_dataset",
        "refund_account",
        "risk_agent",
        "supervisor_dispatch",
    }
)

#: Обязательные реальные реализации для AI-workflow расширения (ADR-0409).
_REQUIRED_TARGETS = {
    "code_interpreter_loop": "extensions.credit_pipeline.sandbox:execute_code",
    "multi_agent_supervisor": "extensions.credit_pipeline.supervisor:supervise",
}


@pytest.fixture(scope="module")
def core_actions() -> object:
    """Заполнить action-реестр ядровыми actions (регистрация глобальная).

    Yields:
        Реестр actions ядра.

    """
    saved = dict(action_handler_registry._handlers)
    register_action_handlers()
    try:
        yield action_handler_registry
    finally:
        action_handler_registry._handlers.clear()
        action_handler_registry._handlers.update(saved)


def _workflow_files() -> list[Path]:
    """Все YAML-декларации workflow расширений.

    Returns:
        Список путей к ``extensions/*/workflows/*.workflow.yaml``.

    """
    return sorted(EXTENSIONS_DIR.rglob("*.workflow.yaml"))


def _activity_steps(declaration: object) -> list[object]:
    """Activity-шаги декларации (включая шаги saga).

    Args:
        declaration: WorkflowDeclaration.

    Returns:
        Список шагов с activity-таргетом.

    """
    steps: list[object] = []
    for step in declaration.steps:  # type: ignore[attr-defined]
        step_type = getattr(step, "type", "")
        if step_type in ("activity", "call_function"):
            steps.append(step)
        elif step_type == "saga":
            steps.extend(step.forward)
            steps.extend(step.compensate)
    return steps


def _target_name(step: object) -> str:
    """Имя activity-цели шага (name или ref).

    Args:
        step: Шаг декларации.

    Returns:
        Имя цели.

    """
    return getattr(step, "name", None) or getattr(step, "ref", "")


@pytest.mark.parametrize("workflow_yaml", _workflow_files(), ids=lambda path: path.name)
def test_workflow_targets_exist(workflow_yaml: Path, core_actions: object) -> None:
    """Каждый шаг ссылается на существующую цель (action или callable)."""
    declaration = load_workflow_from_yaml(workflow_yaml.read_text(encoding="utf-8"))

    for step in _activity_steps(declaration):
        name = _target_name(step)
        assert name, f"{workflow_yaml.name}: шаг без имени activity"
        if is_call_function_ref(name):
            module_name, _, attr = name.partition(":")
            module = importlib.import_module(module_name)
            assert callable(getattr(module, attr, None)), (
                f"{workflow_yaml.name}: {name} — цель не является callable"
            )
        else:
            assert action_handler_registry.is_registered(name), (
                f"{workflow_yaml.name}: {name} — action не зарегистрирован в ядре"
            )


@pytest.mark.parametrize("workflow_yaml", _workflow_files(), ids=lambda path: path.name)
def test_call_function_targets_accept_single_payload(
    workflow_yaml: Path, core_actions: object
) -> None:
    """module:fn-цель принимает ровно один позиционный аргумент (payload)."""
    declaration = load_workflow_from_yaml(workflow_yaml.read_text(encoding="utf-8"))

    for step in _activity_steps(declaration):
        name = _target_name(step)
        if not is_call_function_ref(name):
            continue
        module_name, _, attr = name.partition(":")
        module = importlib.import_module(module_name)
        func = getattr(module, attr)
        signature = inspect.signature(func)
        positional = [
            param
            for param in signature.parameters.values()
            if param.kind
            in (param.POSITIONAL_ONLY, param.POSITIONAL_OR_KEYWORD)
        ]
        required = [
            param
            for param in positional
            if param.default is inspect.Parameter.empty
        ]
        assert len(required) <= 1, (
            f"{workflow_yaml.name}: {name} принимает {len(required)} обязательных "
            "позиционных аргументов — call_function вызывает её как fn(payload)"
        )


@pytest.mark.parametrize("workflow_yaml", _workflow_files(), ids=lambda path: path.name)
def test_call_function_args_are_flat_payload(
    workflow_yaml: Path, core_actions: object
) -> None:
    """Args module:fn-шага — сам payload, без вложенных обёрток."""
    declaration = load_workflow_from_yaml(workflow_yaml.read_text(encoding="utf-8"))

    for step in _activity_steps(declaration):
        name = _target_name(step)
        if not is_call_function_ref(name):
            continue
        args = dict(getattr(step, "args", {}) or {})
        wrappers = sorted(_PAYLOAD_WRAPPER_KEYS.intersection(args))
        assert not wrappers, (
            f"{workflow_yaml.name}: {name} — payload обёрнут в {wrappers}; "
            "call_function передаёт args напрямую (fn(payload))"
        )


@pytest.mark.parametrize("workflow_yaml", _workflow_files(), ids=lambda path: path.name)
def test_decision_agent_receives_scoring_output(workflow_yaml: Path) -> None:
    """``decision_agent`` получает вывод ``scoring_agent``, а не чужой шаг."""
    declaration = load_workflow_from_yaml(workflow_yaml.read_text(encoding="utf-8"))
    steps = list(declaration.steps)

    for index, step in enumerate(steps):
        if _target_name(step) != "extensions.credit_pipeline.agents:decision_agent":
            continue
        args = dict(getattr(step, "args", {}) or {})
        reference = str(args.get("scoring_agent", ""))
        assert reference.startswith("${{ steps."), (
            f"{workflow_yaml.name}: decision_agent без ссылки на шаг скоринга"
        )
        source_index = int(reference.split("steps.")[1].split("}")[0].strip())
        assert source_index < index, (
            f"{workflow_yaml.name}: decision_agent ссылается на будущий шаг"
        )
        source_target = _target_name(steps[source_index])
        assert source_target == "extensions.credit_pipeline.agents:scoring_agent", (
            f"{workflow_yaml.name}: decision_agent получает вывод "
            f"'{source_target}' вместо scoring_agent"
        )


@pytest.mark.parametrize("workflow_yaml", _workflow_files(), ids=lambda path: path.name)
def test_no_fictional_targets(workflow_yaml: Path) -> None:
    """Вымышленные activity-имена не возвращаются в декларации."""
    declaration = load_workflow_from_yaml(workflow_yaml.read_text(encoding="utf-8"))

    for step in _activity_steps(declaration):
        name = _target_name(step)
        bare = name.rpartition(":")[2] if is_call_function_ref(name) else name
        assert bare not in _FICTIONAL_TARGETS, (
            f"{workflow_yaml.name}: ссылка на вымышленную activity '{name}'"
        )


@pytest.mark.parametrize("workflow_name", sorted(_REQUIRED_TARGETS))
def test_ai_workflows_use_real_implementations(workflow_name: str) -> None:
    """AI-workflow расширения ссылаются на реальные реализации (ADR-0409).

    ``code_interpreter_loop`` обязан исполнять код в sandbox'е, а
    ``multi_agent_supervisor`` — раздавать заявку супервизором; LLM-вызов
    ``ai.run_agent`` этими ролями НЕ является.
    """
    matches = [
        path
        for path in _workflow_files()
        if load_workflow_from_yaml(path.read_text(encoding="utf-8")).name == workflow_name
    ]
    assert matches, f"workflow '{workflow_name}' не найден"

    declaration = load_workflow_from_yaml(matches[0].read_text(encoding="utf-8"))
    targets = {_target_name(step) for step in _activity_steps(declaration)}
    assert _REQUIRED_TARGETS[workflow_name] in targets, (
        f"{workflow_name}: нет реальной реализации "
        f"'{_REQUIRED_TARGETS[workflow_name]}' (targets: {sorted(targets)})"
    )
