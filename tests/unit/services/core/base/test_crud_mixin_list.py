"""Regression-блокировка для NEW-1c fix: <service>.list method.

Pre-NEW-1c: auto-router регистрировал ``*.list`` actions (через
``_CRUD_METHODS = ("add", "get", "update", "delete")`` — БЕЗ ``list``).
Любой вызов ``/api/v1/auto/orders.list`` → 500 ``AttributeError:
'OrderService' object has no attribute 'list'``.

NEW-1c fix (2026-08-13):
1. ``_CRUD_METHODS`` расширен до ``("add", "list", "get", "update", "delete")``
2. ``CrudMixin.list`` добавлен: возвращает ``repo.get_paginated()``
   (default — все записи, без пагинации).

Тесты:

1. ``CrudMixin.list`` существует и callable (async coroutine).
2. ``_CRUD_METHODS`` содержит ``"list"``.
3. ``list`` (async) вызывает ``repo.get_paginated()`` с правильными args.
4. list возвращает список items (если repo.get_paginated возвращает dict).
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock


def test_crud_mixin_has_list_method() -> None:
    """CrudMixin.list существует и callable (NEW-1c fix)."""
    from src.backend.services.core.base.crud_mixin import CrudMixin

    assert hasattr(CrudMixin, "list"), "CrudMixin.list missing (NEW-1c fix regressed)"
    assert callable(getattr(CrudMixin, "list")), "CrudMixin.list not callable"


def test_crud_methods_contains_list() -> None:
    """_CRUD_METHODS содержит 'list' (NEW-1c fix)."""
    from src.backend.dsl.service_dsl import _CRUD_METHODS

    assert "list" in _CRUD_METHODS, (
        f"NEW-1c fix regressed: _CRUD_METHODS = {_CRUD_METHODS}, "
        f"missing 'list'"
    )


def test_list_calls_repo_get_paginated() -> None:
    """CrudMixin.list вызывает repo.get_paginated() с правильными args (async)."""
    from src.backend.services.core.base.crud_mixin import CrudMixin

    class _NoOpBoundary:
        """No-op async context manager (заменяет AsyncMock который не поддерживает)."""
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

    class _TestService:
        list = CrudMixin.list
        _service_error_boundary = _NoOpBoundary

        def __init__(self, repo):
            self.repo = repo

    fake_repo = MagicMock()
    fake_repo.get_paginated = AsyncMock(
        return_value={"items": ["a", "b"], "total": 2}
    )

    svc = _TestService(repo=fake_repo)
    result = asyncio.run(svc.list(limit=10, offset=0, by="id", order="asc"))

    # Проверяем что get_paginated был вызван с правильными args
    fake_repo.get_paginated.assert_called_once()
    assert result == ["a", "b"]


def test_list_returns_empty_when_no_items() -> None:
    """list возвращает [] когда get_paginated вернул пустой dict (async)."""
    from src.backend.services.core.base.crud_mixin import CrudMixin

    class _NoOpBoundary:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

    class _TestService:
        list = CrudMixin.list
        _service_error_boundary = _NoOpBoundary

        def __init__(self, repo):
            self.repo = repo

    fake_repo = MagicMock()
    fake_repo.get_paginated = AsyncMock(return_value={"items": []})

    svc = _TestService(repo=fake_repo)
    result = asyncio.run(svc.list())

    assert result == []
