"""Unit-тесты ``services.notifications`` — coverage ratchet (Post-Plan A Sprint 5).

core/notifications service package facade: re-exports ``AppriseNotificationService``
+ ``get_notification_service`` singleton. ~5 stmts, 0% coverage.

Цель slice: 0% → 100% через __all__ audit + class/callable identity.
"""

from __future__ import annotations

import pytest

from src.backend.services import notifications
from src.backend.services.notifications import (
    AppriseNotificationService,
    get_notification_service,
)


@pytest.mark.unit
class TestNotificationsFacadeAllExports:
    """``__all__`` audit + class/function identity."""

    @pytest.mark.parametrize(
        "symbol_name",
        ["AppriseNotificationService", "get_notification_service"],
    )
    def test_all_exports_accessible(self, symbol_name: str) -> None:
        """Каждый символ из ``__all__`` доступен через facade."""
        assert hasattr(notifications, symbol_name), (
            f"Missing export: {symbol_name}"
        )
        assert symbol_name in notifications.__all__, (
            f"{symbol_name} not declared in __all__"
        )

    def test_all_declared_count(self) -> None:
        """``__all__`` содержит 2 символа."""
        assert len(notifications.__all__) == 2

    def test_module_docstring_present(self) -> None:
        """Module docstring описывает Apprise multi-channel уведомления."""
        assert notifications.__doc__ is not None
        assert "Apprise" in notifications.__doc__ or "уведомлен" in notifications.__doc__


@pytest.mark.unit
class TestNotificationsFacadeIdentity:
    """Identity checks для re-exports."""

    def test_apprise_notification_service_is_class(self) -> None:
        """``AppriseNotificationService`` — class (multi-channel sender)."""
        assert isinstance(AppriseNotificationService, type)

    def test_get_notification_service_is_callable(self) -> None:
        """``get_notification_service`` — callable (singleton getter)."""
        assert callable(get_notification_service)
