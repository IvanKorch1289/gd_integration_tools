"""ADR-0424 — каталог шаблонов workflow: контракты, теги, покрытие типов шагов.

Проверяются инварианты каталога ``src/backend/dsl/workflow/templates``:

1. каждый шаблон валиден по спеке (``WorkflowDeclaration``);
2. каждый шаблон резолвится против action-реестра
   (``ActivityBridge.collect_activities(validate=True)`` — как в ADR-0395);
3. каждый шаблон объявляет поле ``tags:`` (машиночитаемые теги для
   подписок/фильтров) и они совпадают с конвенцией ``Template tags:`` в
   description;
4. каждый тип шага, встречающийся в шаблонах, покрыт сценарием
   (сценарий = минимальная валидная декларация с таким шагом);
5. новые шаблоны содержат заявленные в ADR-0424 контракты
   (``call_function``/``compensate_map``/``on_timeout``/``guardrail``/
   ``memory_scope``/``sensor.timeout_s``/``sla``/``checkpoint``).
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest
import yaml

from src.backend.dsl.commands.action_registry import action_handler_registry
from src.backend.dsl.commands.setup import register_action_handlers
from src.backend.dsl.workflow.compiler.activity_bridge import ActivityBridge
from src.backend.dsl.workflow.spec import WorkflowDeclaration

_TEMPLATES_DIR = (
    Path(__file__).resolve().parents[4]
    / "src"
    / "backend"
    / "dsl"
    / "workflow"
    / "templates"
)

#: Шаблоны, добавленные ADR-0424 (каталог вырос с 10 до 18).
_NEW_TEMPLATES = (
    "agent_pipeline",
    "call_function_ingest",
    "checkpoint_continue_as_new",
    "guardrail_cost_budget",
    "hitl_approval_chain",
    "saga_compensation_map",
    "sensor_polling",
    "sla_retry_policy",
)


def _template_paths() -> list[Path]:
    """Список файлов шаблонов workflow (отсортирован)."""
    return sorted(_TEMPLATES_DIR.glob("*.workflow.yaml"))


def _raw(path: Path) -> dict[str, Any]:
    """Сырой dict шаблона (без валидации спеком)."""
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert isinstance(data, dict), f"{path.name}: ожидался YAML-mapping"
    return data


def _declaration(path: Path) -> WorkflowDeclaration:
    """Валидированная декларация шаблона."""
    return WorkflowDeclaration.model_validate(_raw(path))


def _description_tags(description: str) -> tuple[str, ...]:
    """Теги из конвенции ``Template tags: a, b, c.`` в description."""
    marker = "Template tags:"
    if marker not in description:
        return ()
    tail = description.split(marker, 1)[1].split(".", 1)[0]
    return tuple(t.strip() for t in tail.split(",") if t.strip())


@pytest.fixture
def core_action_registry() -> Any:
    """Заполнить action-реестр ядровыми actions и вернуть его как было."""
    saved = dict(action_handler_registry._handlers)
    register_action_handlers()
    try:
        yield action_handler_registry
    finally:
        action_handler_registry._handlers.clear()
        action_handler_registry._handlers.update(saved)


# ── (1) Спека ────────────────────────────────────────────────────────


@pytest.mark.unit
def test_every_template_validates_against_workflow_spec() -> None:
    """Каждый шаблон каталога — валидная ``WorkflowDeclaration``."""
    paths = _template_paths()
    assert paths, "шаблоны workflow не найдены"

    for path in paths:
        decl = _declaration(path)
        assert decl.name == path.stem.removesuffix(".workflow"), path.name
        assert decl.steps, f"{path.name}: нет шагов"


@pytest.mark.unit
def test_new_templates_are_shipped() -> None:
    """Каталог содержит 8 новых шаблонов ADR-0424."""
    names = {p.stem.removesuffix(".workflow") for p in _template_paths()}
    assert set(_NEW_TEMPLATES) <= names


# ── (2) Build-time резолв activity ──────────────────────────────────


@pytest.mark.unit
def test_every_template_resolves_activities(core_action_registry: Any) -> None:
    """Шаблоны резолвятся против action-реестра (ADR-0395/ADR-0398)."""
    for path in _template_paths():
        decl = _declaration(path)
        bridge = ActivityBridge()
        activities = bridge.collect_activities([decl], validate=True)
        assert activities, f"{path.name}: ни одной activity не собрано"


# ── (3) Теги ─────────────────────────────────────────────────────────


@pytest.mark.unit
def test_every_template_declares_machine_readable_tags() -> None:
    """Каждый шаблон объявляет непустое поле ``tags:``."""
    for path in _template_paths():
        tags = _raw(path).get("tags")
        assert isinstance(tags, list), f"{path.name}: нет поля tags:"
        assert tags, f"{path.name}: пустой tags:"
        assert all(isinstance(t, str) and t for t in tags), path.name
        assert len(set(tags)) == len(tags), f"{path.name}: дубли тегов"


@pytest.mark.unit
def test_template_tags_match_description_convention() -> None:
    """Поле ``tags:`` совпадает с конвенцией ``Template tags:`` в description.

    Конвенция в description — legacy-контракт
    ``WorkflowTemplateRegistry``; поле ``tags:`` — канонический источник.
    Расхождение = дрейф, который ломает фильтры каталога.
    """
    for path in _template_paths():
        raw = _raw(path)
        declared = tuple(raw["tags"])
        from_description = _description_tags(str(raw.get("description", "")))
        assert from_description, f"{path.name}: нет конвенции Template tags:"
        assert declared == from_description, path.name


# ── (4) Покрытие типов шагов сценариями ─────────────────────────────


def _scenario_activity() -> WorkflowDeclaration:
    """Сценарий: activity-шаг (имя — зарегистрированный action)."""
    return WorkflowDeclaration.model_validate(
        {
            "name": "scenario.activity",
            "steps": [
                {
                    "type": "activity",
                    "name": "users.list",
                    "args": {"limit": 1},
                    "timeout_s": 30,
                }
            ],
        }
    )


def _scenario_call_function() -> WorkflowDeclaration:
    """Сценарий: call_function-шаг (``module:fn`` + output_key)."""
    return WorkflowDeclaration.model_validate(
        {
            "name": "scenario.call_function",
            "steps": [
                {
                    "type": "call_function",
                    "ref": "src.backend.core.utils.json_utils:dumps_str",
                    "args": {"payload": {}},
                    "timeout_s": 30,
                    "output_key": "canonical_json",
                }
            ],
        }
    )


def _scenario_saga() -> WorkflowDeclaration:
    """Сценарий: saga с explicit ``compensate_map`` + ``strict_compensate``."""
    return WorkflowDeclaration.model_validate(
        {
            "name": "scenario.saga",
            "steps": [
                {
                    "type": "saga",
                    "strict_compensate": True,
                    "forward": [
                        {
                            "type": "activity",
                            "name": "users.add",
                            "args": {"data": {}},
                            "timeout_s": 30,
                        }
                    ],
                    "compensate": [
                        {
                            "type": "activity",
                            "name": "users.update",
                            "args": {"key": "id", "value": 0},
                            "timeout_s": 30,
                        }
                    ],
                    "compensate_map": {"users.add": "users.update"},
                }
            ],
        }
    )


def _scenario_wait_signal() -> WorkflowDeclaration:
    """Сценарий: wait_signal с ``on_timeout`` и ``output_key``."""
    return WorkflowDeclaration.model_validate(
        {
            "name": "scenario.wait_signal",
            "steps": [
                {
                    "type": "wait_signal",
                    "signal_name": "approved",
                    "timeout_s": 60,
                    "on_timeout": "raise",
                    "output_key": "decision",
                }
            ],
        }
    )


def _scenario_guardrail() -> WorkflowDeclaration:
    """Сценарий: guardrail (лимит стоимости)."""
    return WorkflowDeclaration.model_validate(
        {
            "name": "scenario.guardrail",
            "steps": [
                {
                    "type": "guardrail",
                    "rule": "max_cost_usd",
                    "threshold": 0.5,
                    "on_exceed": "fail",
                    "output_key": "cost_guard",
                }
            ],
        }
    )


def _scenario_escalate() -> WorkflowDeclaration:
    """Сценарий: escalate на другого агента."""
    return WorkflowDeclaration.model_validate(
        {
            "name": "scenario.escalate",
            "steps": [
                {
                    "type": "escalate",
                    "to_agent": "senior_advisor",
                    "reason": "budget_exceeded",
                    "output_key": "escalation",
                }
            ],
        }
    )


def _scenario_reflect() -> WorkflowDeclaration:
    """Сценарий: reflect (procedural memory update)."""
    return WorkflowDeclaration.model_validate(
        {
            "name": "scenario.reflect",
            "steps": [
                {
                    "type": "reflect",
                    "source_step": "agent_answer",
                    "memory_writes": ["episodic", "semantic"],
                    "consolidation_policy": "reflect",
                    "async_mode": True,
                    "output_key": "reflection",
                }
            ],
        }
    )


def _scenario_agent_invoke() -> WorkflowDeclaration:
    """Сценарий: agent_invoke со scoped memory."""
    return WorkflowDeclaration.model_validate(
        {
            "name": "scenario.agent_invoke",
            "steps": [
                {
                    "type": "agent_invoke",
                    "agent_id": "credit_advisor",
                    "input_context": "${body.user_input}",
                    "durable": True,
                    "max_turns": 8,
                    "timeout_s": 600,
                    "output_key": "agent_answer",
                    "memory_scope": {
                        "read": ["episodic", "semantic"],
                        "write": ["episodic"],
                        "mode": "scoped",
                        "write_strategy": "background",
                    },
                    "write_episode": True,
                    "inject_memory": True,
                    "recall_on": "body.query",
                }
            ],
        }
    )


def _scenario_sensor() -> WorkflowDeclaration:
    """Сценарий: sensor с ``module:fn``-предикатом и явным timeout_s."""
    return WorkflowDeclaration.model_validate(
        {
            "name": "scenario.sensor",
            "steps": [
                {
                    "type": "sensor",
                    "predicate": "src.backend.dsl.helpers.banking:validate_inn",
                    "poll_interval_s": 30,
                    "timeout_s": 900,
                }
            ],
        }
    )


def _scenario_checkpoint() -> WorkflowDeclaration:
    """Сценарий: checkpoint состояния workflow."""
    return WorkflowDeclaration.model_validate(
        {
            "name": "scenario.checkpoint",
            "steps": [
                {
                    "type": "checkpoint",
                    "checkpoint_id": "scenario_chk",
                    "include_steps": ["batch"],
                    "metadata": {"stage": "pre_rotate"},
                    "output_key": "checkpoint",
                }
            ],
        }
    )


def _scenario_continue_as_new() -> WorkflowDeclaration:
    """Сценарий: continue_as_new (чистая история execution)."""
    return WorkflowDeclaration.model_validate(
        {
            "name": "scenario.continue_as_new",
            "steps": [
                {
                    "type": "continue_as_new",
                    "same_workflow_id": True,
                    "same_input": True,
                    "search_attributes": {},
                }
            ],
        }
    )


#: Сценарий на каждый тип шага, встречающийся в каталоге шаблонов.
_STEP_TYPE_SCENARIOS: dict[str, Callable[[], WorkflowDeclaration]] = {
    "activity": _scenario_activity,
    "agent_invoke": _scenario_agent_invoke,
    "call_function": _scenario_call_function,
    "checkpoint": _scenario_checkpoint,
    "continue_as_new": _scenario_continue_as_new,
    "escalate": _scenario_escalate,
    "guardrail": _scenario_guardrail,
    "reflect": _scenario_reflect,
    "saga": _scenario_saga,
    "sensor": _scenario_sensor,
    "wait_signal": _scenario_wait_signal,
}


@pytest.mark.unit
def test_every_template_step_type_has_scenario() -> None:
    """Каждый тип шага из каталога покрыт сценарием."""
    used: set[str] = set()
    for path in _template_paths():
        used.update(step.type for step in _declaration(path).steps)

    assert used, "в шаблонах не найдено ни одного шага"
    assert not (used - set(_STEP_TYPE_SCENARIOS)), (
        f"типы шагов без сценария: {sorted(used - set(_STEP_TYPE_SCENARIOS))}"
    )


@pytest.mark.unit
@pytest.mark.parametrize("step_type", sorted(_STEP_TYPE_SCENARIOS))
def test_scenario_covers_step_type(step_type: str) -> None:
    """Сценарий строит валидную декларацию с шагом данного типа."""
    decl = _STEP_TYPE_SCENARIOS[step_type]()
    assert any(step.type == step_type for step in decl.steps)
    assert decl.steps


# ── (5) Контракты новых шаблонов ────────────────────────────────────


@pytest.mark.unit
def test_call_function_ingest_template_contract() -> None:
    """``call_function_ingest``: call_function + ref(module:fn) + output_key."""
    raw = _raw(_TEMPLATES_DIR / "call_function_ingest.workflow.yaml")
    steps = raw["steps"]
    call_steps = [s for s in steps if s["type"] == "call_function"]
    assert call_steps, "нет шага call_function"
    for step in call_steps:
        assert ":" in step["ref"], step
        module, _, func = step["ref"].partition(":")
        assert module and func, step
        assert step.get("output_key"), step


@pytest.mark.unit
def test_saga_compensation_map_template_contract() -> None:
    """``saga_compensation_map``: compensate_map + strict_compensate: true."""
    raw = _raw(_TEMPLATES_DIR / "saga_compensation_map.workflow.yaml")
    sagas = [s for s in raw["steps"] if s["type"] == "saga"]
    assert sagas, "нет saga-шага"
    for saga in sagas:
        assert saga.get("strict_compensate") is True, saga
        mapping = saga.get("compensate_map")
        assert mapping, saga
        forward = {s["name"] for s in saga["forward"]}
        compensate = {s["name"] for s in saga["compensate"]}
        for fwd, comp in mapping.items():
            assert fwd in forward, saga
            assert comp in compensate, saga


@pytest.mark.unit
def test_hitl_approval_chain_template_contract() -> None:
    """``hitl_approval_chain``: wait_signal c on_timeout (raise|continue)."""
    raw = _raw(_TEMPLATES_DIR / "hitl_approval_chain.workflow.yaml")
    waits = [s for s in raw["steps"] if s["type"] == "wait_signal"]
    assert len(waits) >= 2, "ожидались raise- и continue-варианты"
    timeouts = {w.get("on_timeout") for w in waits}
    assert timeouts == {"raise", "continue"}, waits
    for wait in waits:
        assert wait.get("output_key"), wait
        assert wait.get("signal_name"), wait
        assert wait.get("timeout_s"), wait


@pytest.mark.unit
def test_every_guardrail_step_has_explicit_target() -> None:
    """Guardrail-шаг обязан иметь явный числовой ``target`` (ADR-0429).

    Без ``target`` guardrail берёт последний output шага — обычно строку
    ответа агента → ``GuardrailValueTypeError`` (fail-closed, D-A8-07),
    т.е. шаблон не запускается. Явный ``target`` (в т.ч. dot-path
    ``usage.cost_usd``) делает проверку детерминированной.
    """
    for path in _template_paths():
        raw = _raw(path)
        for step in raw.get("steps", []):
            if step.get("type") != "guardrail":
                continue
            assert step.get("target"), (
                f"{path.name}: guardrail без target → берёт последний output "
                "(обычно нечисловой) и падает с GuardrailValueTypeError"
            )


@pytest.mark.unit
def test_guardrail_cost_budget_template_contract() -> None:
    """``guardrail_cost_budget``: guardrail (fail|warn) + escalate + reflect."""
    raw = _raw(_TEMPLATES_DIR / "guardrail_cost_budget.workflow.yaml")
    types = [s["type"] for s in raw["steps"]]
    assert "guardrail" in types
    assert "escalate" in types
    assert "reflect" in types
    actions = {s["on_exceed"] for s in raw["steps"] if s["type"] == "guardrail"}
    assert actions == {"fail", "warn"}, actions


@pytest.mark.unit
def test_agent_pipeline_template_contract() -> None:
    """``agent_pipeline``: agent_invoke + memory_scope + escalate."""
    raw = _raw(_TEMPLATES_DIR / "agent_pipeline.workflow.yaml")
    types = [s["type"] for s in raw["steps"]]
    assert "agent_invoke" in types
    assert "escalate" in types
    agent_steps = [s for s in raw["steps"] if s["type"] == "agent_invoke"]
    for step in agent_steps:
        scope = step.get("memory_scope")
        assert scope, step
        assert scope.get("mode"), scope
        assert scope.get("read") is not None, scope


@pytest.mark.unit
def test_sensor_polling_template_contract() -> None:
    """``sensor_polling``: sensor c module:fn-предикатом и timeout_s."""
    raw = _raw(_TEMPLATES_DIR / "sensor_polling.workflow.yaml")
    sensors = [s for s in raw["steps"] if s["type"] == "sensor"]
    assert sensors, "нет sensor-шага"
    for sensor in sensors:
        predicate = sensor["predicate"]
        module, _, func = predicate.partition(":")
        assert module and func, sensor
        assert sensor.get("timeout_s"), "sensor без timeout_s (D-A8-10)"
        assert sensor.get("poll_interval_s"), sensor


@pytest.mark.unit
def test_sla_retry_policy_template_contract() -> None:
    """``sla_retry_policy``: полный top-level контракт."""
    raw = _raw(_TEMPLATES_DIR / "sla_retry_policy.workflow.yaml")
    assert raw.get("sla"), "нет sla:"
    sla = raw["sla"]
    assert sla.get("soft_limit_seconds"), sla
    assert sla.get("hard_limit_seconds"), sla
    assert raw.get("default_timeout_s"), "нет default_timeout_s"
    retry = raw.get("default_retry_policy")
    assert retry, "нет default_retry_policy:"
    assert retry.get("max_attempts"), retry
    assert raw.get("tags"), "нет tags:"


@pytest.mark.unit
def test_checkpoint_continue_as_new_template_contract() -> None:
    """``checkpoint_continue_as_new``: checkpoint + continue_as_new."""
    raw = _raw(_TEMPLATES_DIR / "checkpoint_continue_as_new.workflow.yaml")
    types = [s["type"] for s in raw["steps"]]
    assert "checkpoint" in types
    assert "continue_as_new" in types


# ── (6) CLI-генератор workflow ──────────────────────────────────────


@pytest.mark.unit
def test_cli_generated_workflow_is_spec_valid() -> None:
    """``dsl generate workflow`` выдаёт YAML, валидный по спеке workflow.

    Регрессия: генератор отдавал ``{"workflow": {...}}`` с route-DSL
    шагами (``processor``/``params``) — такой файл не загружается
    ``WorkflowDeclaration`` (extra=forbid) и вводит в заблуждение.
    """
    from src.backend.dsl.cli.generate import _build_workflow_template

    template = _build_workflow_template("cli-scaffold", steps=2)

    decl = WorkflowDeclaration.model_validate(template)
    assert decl.name == "cli-scaffold"
    assert len(decl.steps) == 2
    assert decl.tags
    assert "workflow" not in template
