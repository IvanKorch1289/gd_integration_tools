"""ADR-0403: activity-имена в YAML-декларациях расширений резолвятся.

Дефект (до фикса)
-----------------
``extensions/credit_pipeline/workflows/*.yaml`` ссылались на activity-имена,
которых нет ни в action-реестре ядра, ни среди ``module:fn``-ссылок
расширения: ``receive_dataset``, ``llm_propose_code``,
``execute_code_sandboxed``, ``evaluate_results``, ``format_final_report``,
``collect_loan_inputs``, ``supervisor_dispatch``, ``risk_agent``,
``compliance_agent``, ``scoring_agent``, ``consolidate_results``,
``final_decision``, ``fetch_credit_data``, ``rag_query_legal_policies``,
``llm_credit_decision``.

ADR-0398 включил build-time резолв activity
(``collect_activities(declarations, validate=True)``) — worker Temporal
падал на старте с ``UnknownActivityError`` (список неизвестных имён),
т.к. auto-load подхватывает ``extensions/*/workflows/*.workflow.yaml``.

Ожидание
--------
Для каждой YAML-декларации расширения build-time резолв проходит: каждое
activity-имя либо зарегистрировано в action-реестре ядра, либо является
``module:fn``-ссылкой на реально существующий callable.
"""

from __future__ import annotations

import importlib
from pathlib import Path

import pytest

from src.backend.dsl.commands.action_registry import action_handler_registry
from src.backend.dsl.commands.setup import register_action_handlers
from src.backend.dsl.portal import load_workflow_from_yaml
from src.backend.dsl.workflow.compiler.activity_bridge import ActivityBridge

pytestmark = pytest.mark.unit

REPO_ROOT = Path(__file__).resolve().parents[4]
EXTENSIONS_DIR = REPO_ROOT / "extensions"


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


def test_extension_workflow_files_exist() -> None:
    """В репозитории есть YAML-декларации workflow расширений."""
    assert _workflow_files(), "YAML-декларации workflow расширений не найдены"


@pytest.mark.parametrize("workflow_yaml", _workflow_files(), ids=lambda path: path.name)
def test_extension_workflow_activities_resolve(
    workflow_yaml: Path, core_actions: object
) -> None:
    """Build-time резолв activity проходит для каждой декларации расширения."""
    declaration = load_workflow_from_yaml(workflow_yaml.read_text(encoding="utf-8"))

    activities = ActivityBridge().collect_activities([declaration], validate=True)

    assert activities, f"{workflow_yaml.name}: ни одной activity не собрано"


def test_call_function_refs_point_to_real_callables(core_actions: object) -> None:
    """``module:fn``-ссылки деклараций расширений ведут на реальные функции."""
    from src.backend.dsl.workflow.spec import is_call_function_ref

    for workflow_yaml in _workflow_files():
        declaration = load_workflow_from_yaml(workflow_yaml.read_text(encoding="utf-8"))
        for step in declaration.steps:
            names: list[str] = []
            step_type = getattr(step, "type", "")
            if step_type == "activity":
                names.append(step.name)
            elif step_type == "call_function":
                names.append(step.ref)
            elif step_type == "saga":
                names.extend(activity.name for activity in step.forward)
                names.extend(activity.name for activity in step.compensate)
            for name in names:
                if not is_call_function_ref(name):
                    continue
                module_name, _, attr = name.partition(":")
                module = importlib.import_module(module_name)
                assert callable(getattr(module, attr, None)), (
                    f"{workflow_yaml.name}: {name} — цель не является callable"
                )
