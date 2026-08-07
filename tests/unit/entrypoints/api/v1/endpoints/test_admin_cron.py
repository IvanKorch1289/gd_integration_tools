"""Unit-тесты cron-callable whitelist — cycle-6/D-AUDIT-608.

Покрывает API-P0-002 (admin_cron arbitrary RCE): ``_resolve_callable``
до фикса импортировал произвольный модуль, поэтому OPERATOR-админ мог
зарегистрировать ``os:system`` / ``builtins:exec`` и выполнить его через
``POST /admin/cron/{id}/run-now``.
"""

# ruff: noqa: S101

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.backend.entrypoints.api.v1.endpoints.admin_cron import (
    ALLOWED_CALLABLE_MODULES,
    _resolve_callable,
    router,
)

pytest.importorskip("croniter", reason="croniter не установлен")

_WHITELISTED_REF = (
    "src.backend.infrastructure.scheduler.scheduled_tasks:check_all_services"
)

# Модули, доступные в Python path и дающие RCE/data-loss при резолве.
_MALICIOUS_REFS = (
    "os:system",
    "builtins:exec",
    "builtins:eval",
    "builtins:__import__",
    "subprocess:check_output",
    "shutil:rmtree",
)


@pytest.fixture
def client_app() -> TestClient:
    # Тот же bypass require_admin(), что и в tests/unit/entrypoints/
    # test_admin_cron.py — роль super_admin через injected AuthContext.
    app = FastAPI()
    app.include_router(router)

    @app.middleware("http")
    async def _add_auth_context(request, call_next):
        from src.backend.core.auth import AuthContext, AuthMethod

        request.state.auth_context = AuthContext(
            method=AuthMethod.NONE,
            principal="test",
            metadata={"admin_roles": ["super_admin"]},
        )
        return await call_next(request)

    return TestClient(app)


@pytest.mark.parametrize("ref", _MALICIOUS_REFS)
def test_resolve_callable_rejects_non_whitelisted_module(ref: str) -> None:
    """Опасный модуль отвергается до importlib.import_module()."""
    with pytest.raises(ValueError, match="не входит в cron-whitelist"):
        _resolve_callable(ref)


@pytest.mark.parametrize("ref", _MALICIOUS_REFS)
def test_resolve_callable_does_not_import_rejected_module(ref: str) -> None:
    """Отказ происходит без побочного import произвольного модуля."""
    with patch("importlib.import_module") as import_mock:
        with pytest.raises(ValueError, match="не входит в cron-whitelist"):
            _resolve_callable(ref)
    import_mock.assert_not_called()


@pytest.mark.parametrize("ref", _MALICIOUS_REFS)
def test_schedule_rejects_malicious_callable_ref(
    client_app: TestClient, ref: str
) -> None:
    """POST /admin/cron/schedule с опасным callable_ref → 400, job не создан."""
    manager = MagicMock()
    with patch(
        "src.backend.core.scheduler.get_scheduler_manager", return_value=manager
    ):
        response = client_app.post(
            "/admin/cron/schedule",
            json={
                "name": "pwn",
                "cron_expr": "0 9 * * *",
                "callable_ref": ref,
                "timezone": "UTC",
            },
        )

    assert response.status_code == 400
    assert "cron-whitelist" in response.json()["detail"]
    manager.schedule_cron.assert_not_called()


def test_schedule_accepts_whitelisted_callable_ref(client_app: TestClient) -> None:
    """Легитимный whitelisted callable по-прежнему регистрируется (201)."""
    manager = MagicMock()
    manager.schedule_cron.return_value = "job-1"
    manager.list_jobs.return_value = [
        {
            "id": "job-1",
            "name": "healthcheck",
            "next_run_time": "2026-08-06T09:00:00+00:00",
            "trigger": "cron[0 9 * * *]",
            "paused": False,
        }
    ]
    with patch(
        "src.backend.core.scheduler.get_scheduler_manager", return_value=manager
    ):
        response = client_app.post(
            "/admin/cron/schedule",
            json={
                "name": "healthcheck",
                "cron_expr": "0 9 * * *",
                "callable_ref": _WHITELISTED_REF,
                "timezone": "UTC",
            },
        )

    assert response.status_code == 201
    assert response.json()["id"] == "job-1"
    manager.schedule_cron.assert_called_once()


def test_whitelisted_module_resolves_to_callable() -> None:
    """Whitelist указывает на реально существующий импортируемый callable."""
    assert callable(_resolve_callable(_WHITELISTED_REF))


def test_whitelist_contains_only_project_modules() -> None:
    """Whitelist не должен содержать stdlib/третьесторонние модули."""
    assert ALLOWED_CALLABLE_MODULES
    assert all(m.startswith("src.backend.") for m in ALLOWED_CALLABLE_MODULES)


def test_resolve_callable_rejects_non_callable_attribute() -> None:
    """Whitelisted модуль, но атрибут не callable → ValueError."""
    with pytest.raises(ValueError, match="не является callable"):
        _resolve_callable(
            "src.backend.infrastructure.scheduler.scheduled_tasks:__all__"
        )
