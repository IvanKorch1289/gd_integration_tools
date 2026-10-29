"""ADR-0395 — резолв имён activity и поддержка ``call_function``-шага.

Дефект (1): YAML-воркфлоу репозитория нерабочие — имена activity не
резолвятся. ``ActivityBridge`` проксирует вызов в
``action_handler_registry.dispatch``, где 124 action'а и 0 совпадений с
именами шагов; проба давала ``KeyError 'consolidate_results'`` на
``templates/kyc_aml_check.workflow.yaml``. Расширения же используют
идиому route-DSL ``call_function('module:fn')``, которой в workflow-DSL
не было.

Проверяем:
* нормализацию activity-шага ``module:fn`` в ``call_function``-шаг;
* регистрацию activity для ``call_function``-ссылки и её вызов;
* build-time резолв имён против action-реестра;
* понятную ошибку на неизвестном имени.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from src.backend.dsl.commands.action_registry import (
    ActionHandlerRegistry,
    action_handler_registry,
)
from src.backend.dsl.workflow.compiler.activity_bridge import (
    ActivityBridge,
    UnknownActivityError,
    bridge_call_function,
    resolve_activity_target,
)
from src.backend.dsl.workflow.spec import CallFunctionDeclaration, WorkflowDeclaration

_REPO_ROOT = Path(__file__).resolve().parents[4]


def _register_action(name: str, monkeypatch: pytest.MonkeyPatch) -> None:
    """Зарегистрировать action в глобальном реестре (с откатом после теста)."""
    spec = ActionHandlerRegistry  # noqa: F841 — читаемость Intent
    from src.backend.dsl.commands.action_registry import ActionHandlerSpec

    monkeypatch.setitem(
        action_handler_registry._handlers,
        name,
        ActionHandlerSpec(
            action=name, service_getter=lambda: None, service_method="noop"
        ),
    )


class TestCallFunctionSpec:
    """``call_function``-шаг (module:fn) в workflow-спеке."""

    def test_activity_step_with_module_fn_is_normalized(self) -> None:
        """``type: activity`` + ``name: module:fn`` → ``call_function``-шаг."""
        decl = WorkflowDeclaration.model_validate(
            {
                "name": "credit.assessment",
                "steps": [
                    {
                        "type": "activity",
                        "name": "extensions.credit_pipeline.functions.normalize:apply_rules",
                        "args": {"score": 750},
                    }
                ],
            }
        )

        step = decl.steps[0]
        assert isinstance(step, CallFunctionDeclaration)
        assert step.ref == "extensions.credit_pipeline.functions.normalize:apply_rules"
        assert step.args == {"score": 750}

    def test_plain_action_name_stays_activity(self) -> None:
        """Обычное имя action не переписывается."""
        decl = WorkflowDeclaration.model_validate(
            {
                "name": "orders.flow",
                "steps": [{"type": "activity", "name": "orders.create"}],
            }
        )

        assert not isinstance(decl.steps[0], CallFunctionDeclaration)
        assert decl.steps[0].name == "orders.create"

    def test_explicit_call_function_step_is_accepted(self) -> None:
        """Явный ``type: call_function`` валиден."""
        decl = WorkflowDeclaration.model_validate(
            {
                "name": "credit.flow",
                "steps": [
                    {"type": "call_function", "ref": "pkg.mod:fn", "args": {"a": 1}}
                ],
            }
        )

        step = decl.steps[0]
        assert isinstance(step, CallFunctionDeclaration)
        assert step.ref == "pkg.mod:fn"


class TestActivityBridgeCallFunction:
    """ActivityBridge умеет собирать activity для ``call_function``-ссылок."""

    def test_bridge_creates_activity_for_module_fn(self) -> None:
        """``bridge.get('module:fn')`` → activity-callable с таким именем."""
        bridge = ActivityBridge()

        fn = bridge.get("extensions.credit_pipeline.functions.normalize:apply_rules")

        assert fn.__activity_name__ == (  # type: ignore[attr-defined]
            "extensions.credit_pipeline.functions.normalize:apply_rules"
        )

    def test_call_function_activity_executes_target_function(self) -> None:
        """Activity вызывает функцию модуля с payload'ом."""
        fn = bridge_call_function(
            "tests.unit.infrastructure.workflow.test_workflow_declaration_bridge:_sample_target"
        )

        import asyncio

        result = asyncio.run(fn({"x": 1}))
        assert result == {"x": 1, "called": True}

    def test_collect_activities_includes_call_function_step(self) -> None:
        """``collect_activities`` подхватывает call_function-шаги."""
        decl = WorkflowDeclaration.model_validate(
            {
                "name": "credit.flow",
                "steps": [
                    {
                        "type": "call_function",
                        "ref": "tests.unit.infrastructure.workflow.test_workflow_declaration_bridge:_sample_target",
                    }
                ],
            }
        )

        bridge = ActivityBridge()
        names = [fn.__activity_name__ for fn in bridge.collect_activities([decl])]

        assert names == [
            "tests.unit.infrastructure.workflow.test_workflow_declaration_bridge:_sample_target"
        ]


class TestResolveActivityTarget:
    """Build-time резолв имён activity."""

    def test_registered_action_resolves(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Имя из action-реестра резолвится как ``action``."""
        _register_action("orders.create", monkeypatch)

        assert resolve_activity_target("orders.create") == "action"

    def test_module_fn_resolves_as_call_function(self) -> None:
        """``module:fn`` резолвится как ``call_function``."""
        assert resolve_activity_target("pkg.module:fn") == "call_function"

    def test_unknown_name_raises_clear_error(self) -> None:
        """Неизвестное имя → понятная ошибка (не KeyError в рантайме)."""
        with pytest.raises(UnknownActivityError) as exc_info:
            resolve_activity_target("consolidate_results")

        message = str(exc_info.value)
        assert "consolidate_results" in message
        assert "call_function" in message
        assert "module:fn" in message


class TestRepoWorkflowDeclarations:
    """Реальные YAML-декларации репозитория."""

    def test_extension_workflow_resolves_all_activity_names(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """YAML расширения с ``module:fn`` — все activity-имена резолвятся."""
        from src.backend.dsl.workflow.yaml_io import load_workflow_from_file

        yaml_path = (
            _REPO_ROOT
            / "extensions"
            / "credit_pipeline"
            / "workflows"
            / "credit_assessment.workflow.yaml"
        )
        decl = load_workflow_from_file(yaml_path)

        bridge = ActivityBridge()
        activities = bridge.collect_activities([decl], validate=True)

        assert activities, "ожидаются activity-функции для credit_assessment"

    def test_template_workflow_reports_unknown_activity(self) -> None:
        """Шаблон с несуществующим action → понятная ошибка резолва."""
        from src.backend.dsl.workflow.yaml_io import load_workflow_from_file

        yaml_path = (
            _REPO_ROOT
            / "src"
            / "backend"
            / "dsl"
            / "workflow"
            / "templates"
            / "kyc_aml_check.workflow.yaml"
        )
        decl = load_workflow_from_file(yaml_path)

        bridge = ActivityBridge()
        with pytest.raises(UnknownActivityError) as exc_info:
            bridge.collect_activities([decl], validate=True)

        assert "consolidate_results" in str(exc_info.value)


def _sample_target(payload: dict[str, Any]) -> dict[str, Any]:
    """Функция-мишень для теста ``call_function``."""
    return {**payload, "called": True}
