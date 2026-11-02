"""Регрессия: workflow-DI provider возвращает несуществующий атрибут.

Стенд 2026-10-29: ``GET /api/v1/admin/workflows`` отдавал 500 —
``AttributeError: module 'src.backend.infrastructure.database.session_manager'
has no attribute 'get_main_session'``. Provider резолвил
``module.get_main_session``, которого в модуле нет (есть
``get_main_session_manager()`` → :class:`DatabaseSessionManager`).
Потребитель (``admin_workflows/helpers.py``) ждёт объект с методом
``create_session()``.
"""

from __future__ import annotations

from typing import Any

import pytest

__all__ = (
    "TestWorkflowMainSessionProvider",
    "TestWorkflowStateRowClassProvider",
)


class TestWorkflowMainSessionProvider:
    """``get_workflow_main_session_provider`` — валидный session-manager."""

    @pytest.mark.unit
    def test_returns_session_manager(self) -> None:
        """Provider отдаёт объект с ``create_session()`` (без AttributeError)."""
        from src.backend.core.di.providers.workflow import (
            get_workflow_main_session_provider,
        )

        manager: Any = get_workflow_main_session_provider()
        assert manager is not None
        assert callable(getattr(manager, "create_session", None)), (
            "provider должен вернуть DatabaseSessionManager с create_session()"
        )

    @pytest.mark.unit
    def test_override_still_supported(self) -> None:
        """Явный override провайдера по-прежнему работает."""
        from src.backend.core.di.providers.workflow import (
            get_workflow_main_session_provider,
            set_workflow_main_session_provider,
        )

        sentinel = object()
        set_workflow_main_session_provider(sentinel)
        try:
            assert get_workflow_main_session_provider() is sentinel
        finally:
            set_workflow_main_session_provider(None)


class TestWorkflowStateRowClassProvider:
    """``get_workflow_state_row_class_provider`` — существующий row-DTO."""

    @pytest.mark.unit
    def test_returns_row_dto_with_from_orm(self) -> None:
        """Provider отдаёт DTO с ``from_orm`` (без AttributeError)."""
        from src.backend.core.di.providers.workflow import (
            get_workflow_state_row_class_provider,
        )

        row_cls: Any = get_workflow_state_row_class_provider()
        assert row_cls is not None
        assert callable(getattr(row_cls, "from_orm", None))
