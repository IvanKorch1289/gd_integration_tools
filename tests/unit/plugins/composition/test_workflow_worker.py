"""Тесты production wiring standalone workflow worker."""

from __future__ import annotations

from unittest.mock import patch

import pytest

from src.backend.plugins.composition.workflow_worker import register_worker_dependencies


@pytest.mark.unit
def test_register_worker_dependencies_preserves_registration_order() -> None:
    """Composition-адаптер сохраняет прежний порядок регистрации worker'а."""
    calls: list[str] = []

    with (
        patch(
            "src.backend.plugins.composition.service_setup.register_all_services",
            side_effect=lambda: calls.append("services"),
        ),
        patch(
            "src.backend.dsl.commands.setup.orchestrator.register_action_handlers",
            side_effect=lambda: calls.append("actions"),
        ),
        patch(
            "src.backend.dsl.routes.register_dsl_routes",
            side_effect=lambda: calls.append("routes"),
        ),
    ):
        register_worker_dependencies()

    assert calls == ["services", "actions", "routes"]
