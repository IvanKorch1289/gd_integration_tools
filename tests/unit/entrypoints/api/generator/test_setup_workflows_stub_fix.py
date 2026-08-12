"""D-AUDIT-8901: regression-тест workflows_service stub (API-P0-003).

Бывший баг: src/backend/entrypoints/api/generator/setup.py импортировал
`from src.backend.workflows.workflows_service import get_workflows_service`
с `# type: ignore[import-not-found]`. Module был удалён в S168 W13 P2-7,
но import в setup.py остался → register_action_handlers() падал на
startup (`ImportError` / `ModuleNotFoundError`).

Фикс (cycle 89): setup.py больше не импортирует workflows_service. Вместо
этого использует _WorkflowsServiceUnavailable stub (статические методы
бросают NotImplementedError с явным message о миграции на DSL).

Тест проверяет:
1. register_action_handlers() отрабатывает без ImportError
2. workflows.send_email_notification / workflows.order_processing
   регистрируются (test_setup.py требует 6 actions)
3. Service-getter возвращает stub
4. invoke stub.send_notification_workflow() / order_processing_workflow()
   raise NotImplementedError
"""

from __future__ import annotations

import pytest

from src.backend.entrypoints.api.generator import setup as gen_setup
from src.backend.entrypoints.api.generator.registry import ActionHandlerRegistry


@pytest.fixture
def isolated_registry(monkeypatch: pytest.MonkeyPatch) -> ActionHandlerRegistry:
    """Подменить глобальный registry на свежий для теста."""
    from src.backend.entrypoints.api.generator import registry as reg_module

    fresh = ActionHandlerRegistry()
    monkeypatch.setattr(reg_module, "action_handler_registry", fresh)
    monkeypatch.setattr(gen_setup, "_is_registered", False)
    monkeypatch.setattr(gen_setup, "action_handler_registry", fresh)
    return fresh


def test_register_action_handlers_no_import_error(
    isolated_registry: ActionHandlerRegistry,
) -> None:
    """Раньше падал с ModuleNotFoundError на workflows_service."""
    gen_setup.register_action_handlers()
    actions = isolated_registry.list_actions()
    assert "workflows.send_email_notification" in actions
    assert "workflows.order_processing" in actions


def test_workflows_stub_raises_not_implemented() -> None:
    """Service-getter возвращает stub; invoke raise NotImplementedError."""
    stub = gen_setup._get_workflows_service_stub()
    with pytest.raises(NotImplementedError, match="workflows service удалён"):
        stub.send_notification_workflow()
    with pytest.raises(NotImplementedError, match="workflows service удалён"):
        stub.order_processing_workflow()
