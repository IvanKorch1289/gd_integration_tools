"""Shared fixtures для admin endpoint tests (E-1 auth gate).

После E-1 все admin endpoints имеют router-level
``dependencies=[Depends(require_auth([API_KEY, JWT]))]``.

Тонкость: ``require_auth([...])`` возвращает NEW anonymous callable
каждый раз. ``app.dependency_overrides[callable]`` требует тот же
объект. Поэтому override делается через извлечение callable
из ``router.dependencies[0].dependency``.
"""

from __future__ import annotations

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


@pytest.fixture
def authed_admin_app():
    """FastAPI app с правильным auth override для admin routers.

    Использование::

        def test_x(authed_admin_app, some_admin_router):
            authed_admin_app.include_router(some_admin_router, prefix="/admin")
            client = TestClient(authed_admin_app)
            ...

    Override извлекает реальный callable из router.dependencies,
    чтобы dependency_overrides dictionary использовал тот же ключ.
    """

    app = FastAPI()

    # Patch the auth factory itself — все router'ы, загруженные ПОСЛЕ
    # этой fixture, получат bypass callable.
    import src.backend.core.auth.auth_selector as sel

    original = sel.require_auth
    sel.require_auth = lambda methods=None: (lambda request: None)

    yield app

    # Restore (monkeypatch не доступен в фикстуре без параметра,
    # но это test-only context — restore вручную)
    sel.require_auth = original


def make_authed_test_client(router, prefix: str = "/admin") -> TestClient:
    """Helper: build app with auth bypass + mount router + return TestClient."""

    app = FastAPI()

    # Extract the REAL callable from the router (not a fresh one)
    if router.dependencies:
        for dep in router.dependencies:
            if hasattr(dep, "dependency"):
                real_callable = dep.dependency
                app.dependency_overrides[real_callable] = lambda: None
                break

    app.include_router(router, prefix=prefix)
    return TestClient(app)
