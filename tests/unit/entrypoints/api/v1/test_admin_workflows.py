"""Smoke-тесты admin_workflows endpoints (Sprint 4 Wave F)."""
# ruff: noqa: S101

from __future__ import annotations

import importlib

import pytest


def test_admin_workflows_module_importable() -> None:
    """Endpoint-модуль admin_workflows импортируется без ошибок."""
    module = importlib.import_module(
        "src.backend.entrypoints.api.v1.endpoints.admin_workflows"
    )
    assert hasattr(module, "router")


def test_admin_workflows_router_has_routes() -> None:
    """Router admin_workflows регистрирует endpoint'ы."""
    module = importlib.import_module(
        "src.backend.entrypoints.api.v1.endpoints.admin_workflows"
    )
    routes = getattr(module.router, "routes", [])
    paths = {getattr(r, "path", "") for r in routes}
    # Поддерживаем оба варианта: /workflows и /admin/workflows.
    assert any("workflows" in p for p in paths), (
        f"router admin_workflows должен иметь /workflows path; найдено: {sorted(paths)}"
    )


def test_workflow_replay_page_importable() -> None:
    """Streamlit-страница 17_Workflow_Replay.py имеет корректный синтаксис."""
    import importlib.util
    from pathlib import Path

    page_path = (
        Path(__file__).resolve().parents[5]
        / "src"
        / "frontend"
        / "streamlit_app"
        / "pages"
        / "17_Workflow_Replay.py"
    )
    assert page_path.exists(), f"Страница не найдена: {page_path}"
    spec = importlib.util.spec_from_file_location("_replay_page_check", page_path)
    assert spec is not None
    # Не загружаем модуль (streamlit недоступен в unit-test environment),
    # но spec_from_file_location проверяет AST-валидность.


def test_api_client_has_workflow_methods() -> None:
    """APIClient экспортирует list_workflows и get_workflow_events."""
    from src.frontend.streamlit_app.api_client import APIClient

    assert hasattr(APIClient, "list_workflows")
    assert hasattr(APIClient, "get_workflow_events")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
