"""Wave 20 / ADR-0398 — DSL workflow: activity-резолв, sensor, BPMN gateway.

Дефекты проб ре-аудита:

5. [high] Build-time резолв activity в проде выключен
   (``collect_activities`` без ``validate=True``) → 13 из 14 YAML-воркфлоу
   дают Unknown activity; резолвится только ``credit_assessment``.
6. [medium] Activity sensor-предиката не регистрируется →
   ``ActivityNotRegisteredError`` в worker'е.
7. [high] BPMN-ветки gateway не исполняются: target кладётся маркером
   ``{"bpmn_target": ...}``, условие ``${x>=5}`` не парсится simpleeval.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from src.backend.dsl.workflow.bpmn_importer import import_bpmn
from src.backend.dsl.workflow.compiler.activity_bridge import (
    ActivityBridge,
    UnknownActivityError,
)
from src.backend.dsl.workflow.compiler.gateways import (
    _eval_condition,
    _normalize_condition,
)
from src.backend.dsl.workflow.spec import (
    ActivityDeclaration,
    SensorDeclaration,
    WorkflowDeclaration,
)

_TEMPLATES_DIR = (
    Path(__file__).resolve().parents[4]
    / "src"
    / "backend"
    / "dsl"
    / "workflow"
    / "templates"
)


def _make_bpmn(*, body: str, process_id: str = "p1") -> str:
    """Сконструировать минимальный BPMN-XML с заданным body."""
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<bpmn:definitions xmlns:bpmn="http://www.omg.org/spec/BPMN/20100524/MODEL">\n'
        f'  <bpmn:process id="{process_id}" isExecutable="true">\n'
        f"    {body}\n"
        "  </bpmn:process>\n"
        "</bpmn:definitions>\n"
    )


# ── (5) Build-time резолв activity ──────────────────────────────────


@pytest.fixture
def core_action_registry() -> Any:
    """Заполнить action-реестр ядровыми actions и вернуть его как было.

    Регистрация глобальная — без отката она ломает тесты, ожидающие
    «action не зарегистрирован» (например, legacy-alias 404).
    """
    from src.backend.dsl.commands.action_registry import action_handler_registry
    from src.backend.dsl.commands.setup import register_action_handlers

    saved = dict(action_handler_registry._handlers)
    register_action_handlers()
    try:
        yield action_handler_registry
    finally:
        action_handler_registry._handlers.clear()
        action_handler_registry._handlers.update(saved)


@pytest.mark.unit
def test_collect_activities_validate_raises_with_unknown_names() -> None:
    """validate=True падает с перечнем неизвестных activity-имён."""
    decl = WorkflowDeclaration(
        name="wf",
        steps=[
            ActivityDeclaration(name="definitely_unknown_action"),
            ActivityDeclaration(name="another_unknown_action"),
        ],
    )
    bridge = ActivityBridge()

    with pytest.raises(UnknownActivityError) as exc_info:
        bridge.collect_activities([decl], validate=True)

    message = str(exc_info.value)
    assert "definitely_unknown_action" in message
    assert "another_unknown_action" in message


@pytest.mark.unit
def test_shipped_templates_resolve_all_activities(core_action_registry: Any) -> None:
    """Все поставляемые шаблоны workflow резолвятся в action-имена.

    Регрессия: activity-имена в ``templates/*.workflow.yaml`` не были
    зарегистрированы в action-реестре — build-time валидация падала бы
    на 13 из 14 YAML-воркфлоу (ADR-0398).
    """
    from src.backend.dsl.portal import load_workflow_from_yaml

    templates = sorted(_TEMPLATES_DIR.glob("*.workflow.yaml"))
    assert templates, "шаблоны workflow не найдены"

    for template in templates:
        decl = load_workflow_from_yaml(template.read_text(encoding="utf-8"))
        bridge = ActivityBridge()
        activities = bridge.collect_activities([decl], validate=True)
        assert activities, f"{template.name}: ни одной activity не собрано"
    assert core_action_registry.list_actions()


# ── (6) Sensor-предикат регистрируется как activity ─────────────────


@pytest.mark.unit
def test_sensor_predicate_is_registered_as_activity() -> None:
    """Предикат sensor'а — activity: он должен попасть в activity-list."""
    decl = WorkflowDeclaration(
        name="wf",
        steps=[
            SensorDeclaration(
                predicate="pkg.mod:check_ready", poll_interval_s=10.0, timeout_s=60.0
            )
        ],
    )
    bridge = ActivityBridge()

    activities = bridge.collect_activities([decl])

    names = [getattr(fn, "__activity_name__", "") for fn in activities]
    assert "pkg.mod:check_ready" in names


@pytest.mark.unit
def test_sensor_predicate_is_validated_as_activity() -> None:
    """Неизвестный предикат sensor'а ловится build-time валидацией."""
    decl = WorkflowDeclaration(
        name="wf",
        steps=[
            SensorDeclaration(
                predicate="not_registered_predicate",
                poll_interval_s=10.0,
                timeout_s=60.0,
            )
        ],
    )
    bridge = ActivityBridge()

    with pytest.raises(UnknownActivityError) as exc_info:
        bridge.collect_activities([decl], validate=True)

    assert "not_registered_predicate" in str(exc_info.value)


# ── (7) BPMN gateway: ветки исполняются, условие парсится ──────────


@pytest.mark.unit
def test_bpmn_gateway_branch_contains_resolved_activity_steps() -> None:
    """Ветка gateway содержит реальные activity-шаги, а не маркеры."""
    xml = _make_bpmn(
        body="""
        <bpmn:startEvent id="s"/>
        <bpmn:exclusiveGateway id="gw"/>
        <bpmn:serviceTask id="t1" name="branch_a"/>
        <bpmn:serviceTask id="t2" name="branch_b"/>
        <bpmn:endEvent id="e"/>
        <bpmn:sequenceFlow id="f1" sourceRef="s" targetRef="gw"/>
        <bpmn:sequenceFlow id="f2" sourceRef="gw" targetRef="t1"/>
        <bpmn:sequenceFlow id="f3" sourceRef="gw" targetRef="t2"/>
        <bpmn:sequenceFlow id="f4" sourceRef="t1" targetRef="e"/>
        <bpmn:sequenceFlow id="f5" sourceRef="t2" targetRef="e"/>
        """
    )

    decl = import_bpmn(xml, check_feature_flag=False)

    gateway_step = next(
        s
        for s in decl.steps
        if isinstance(s, ActivityDeclaration) and s.name == "__gateway__gw"
    )
    branches = gateway_step.args["gateway"]["branches"]
    assert len(branches) == 2
    for branch in branches:
        assert branch["steps"], "ветка gateway не должна быть пустой"
        assert all(isinstance(step, ActivityDeclaration) for step in branch["steps"]), (
            "маркер bpmn_target не должен попадать в исполняемую ветку"
        )
    assert {b["steps"][0].name for b in branches} == {"branch_a", "branch_b"}


@pytest.mark.unit
def test_bpmn_branch_target_is_not_a_top_level_step() -> None:
    """Task ветки не исполняется всегда — он принадлежит ветке gateway."""
    xml = _make_bpmn(
        body="""
        <bpmn:startEvent id="s"/>
        <bpmn:serviceTask id="t0" name="prepare"/>
        <bpmn:exclusiveGateway id="gw"/>
        <bpmn:serviceTask id="t1" name="branch_a"/>
        <bpmn:serviceTask id="t2" name="branch_b"/>
        <bpmn:endEvent id="e"/>
        <bpmn:sequenceFlow id="f1" sourceRef="s" targetRef="t0"/>
        <bpmn:sequenceFlow id="f2" sourceRef="t0" targetRef="gw"/>
        <bpmn:sequenceFlow id="f3" sourceRef="gw" targetRef="t1"/>
        <bpmn:sequenceFlow id="f4" sourceRef="gw" targetRef="t2"/>
        <bpmn:sequenceFlow id="f5" sourceRef="t1" targetRef="e"/>
        <bpmn:sequenceFlow id="f6" sourceRef="t2" targetRef="e"/>
        """
    )

    decl = import_bpmn(xml, check_feature_flag=False)

    top_level = {s.name for s in decl.steps if isinstance(s, ActivityDeclaration)}
    assert "prepare" in top_level
    assert "branch_a" not in top_level
    assert "branch_b" not in top_level


@pytest.mark.unit
def test_bpmn_branch_chain_is_moved_into_branch() -> None:
    """Цепочка задач ветки (target → следующая task) уезжает в ветку."""
    xml = _make_bpmn(
        body="""
        <bpmn:startEvent id="s"/>
        <bpmn:exclusiveGateway id="gw"/>
        <bpmn:serviceTask id="t1" name="branch_a"/>
        <bpmn:serviceTask id="t1b" name="branch_a_second"/>
        <bpmn:endEvent id="e"/>
        <bpmn:sequenceFlow id="f1" sourceRef="s" targetRef="gw"/>
        <bpmn:sequenceFlow id="f2" sourceRef="gw" targetRef="t1"/>
        <bpmn:sequenceFlow id="f3" sourceRef="t1" targetRef="t1b"/>
        <bpmn:sequenceFlow id="f4" sourceRef="t1b" targetRef="e"/>
        """
    )

    decl = import_bpmn(xml, check_feature_flag=False)

    gateway_step = next(
        s
        for s in decl.steps
        if isinstance(s, ActivityDeclaration) and s.name == "__gateway__gw"
    )
    branch = gateway_step.args["gateway"]["branches"][0]
    assert [step.name for step in branch["steps"]] == ["branch_a", "branch_a_second"]
    top_level = {s.name for s in decl.steps if isinstance(s, ActivityDeclaration)}
    assert "branch_a" not in top_level
    assert "branch_a_second" not in top_level


@pytest.mark.unit
def test_gateway_condition_with_dollar_placeholder_is_evaluated() -> None:
    """``${score} >= 700`` — BPMN formal-expression — вычисляется."""
    ctx = {"_outputs": {"score": 800}}

    assert _eval_condition("${score} >= 700", ctx) is True
    assert _eval_condition("${score} >= 700", {"_outputs": {"score": 100}}) is False


@pytest.mark.unit
def test_gateway_condition_wrapped_in_dollar_braces_is_evaluated() -> None:
    """``${x>=5}`` — вся обёртка — вычисляется."""
    ctx = {"_outputs": {"x": 7}}

    assert _eval_condition("${x>=5}", ctx) is True
    assert _eval_condition("${x>=5}", {"_outputs": {"x": 1}}) is False


@pytest.mark.unit
def test_normalize_condition_strips_bpmn_placeholders() -> None:
    """Нормализация условия снимает ``${...}``-обёртки."""
    assert _normalize_condition("${score} >= 700") == "score >= 700"
    assert _normalize_condition("${x>=5}") == "x>=5"
    assert _normalize_condition("score > 0.8") == "score > 0.8"
