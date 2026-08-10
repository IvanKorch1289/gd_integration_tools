"""D-AUDIT-A3-01 fix (cycle 1): admin AuthZ fail-CLOSED by default.

D-AUDIT-A3-01 (P0): AdminService._authorize ранее silent fail-OPEN —
если AuthorizationGateway unavailable (composition root не подключён),
log warning + return (allow action). Это privilege-escalation vector
при AuthZ outage.

Фикс: fail-CLOSED by default — raise AdminAuthorizationError + emit
audit event с outcome="denied". Opt-in fail-OPEN только через
ADMIN_AUTHZ_FAIL_OPEN=true env var (для dev_light без AuthZ).
"""


from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from src.backend.services.admin.api import AdminAuthorizationError, AdminService


class TestAdminAuthZFailClosed:
    """D-AUDIT-A3-01 fix (cycle 1): admin AuthZ fail-CLOSED by default."""

    @pytest.fixture
    def admin_service_no_authz(self) -> AdminService:
        """AdminService с _get_authz() = None (composition root unavailable).

        Мокаем _get_authz напрямую чтобы избежать auto-resolve через импорты.
        """
        svc = AdminService()
        svc._get_authz = lambda: None  # type: ignore[method-assign]
        return svc

    @pytest.mark.asyncio
    async def test_fail_closed_when_authz_unavailable(
        self, admin_service_no_authz: AdminService, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """D-AUDIT-A3-01 fix: AuthZ unavailable + ADMIN_AUTHZ_FAIL_OPEN не выставлен
        → raise AdminAuthorizationError (fail-CLOSED, было silent fail-OPEN).
        """
        monkeypatch.delenv("ADMIN_AUTHZ_FAIL_OPEN", raising=False)

        with pytest.raises(AdminAuthorizationError) as exc_info:
            await admin_service_no_authz._authorize(
                actor="test_user",
                resource="admin.feature_flag:write",
                action="execute",
            )

        # Verify error message содержит fail-CLOSED hint
        error_msg = str(exc_info.value)
        assert "unavailable" in error_msg.lower() or "fail-closed" in error_msg.lower()

    @pytest.mark.asyncio
    async def test_fail_open_with_explicit_env_opt_in(
        self, admin_service_no_authz: AdminService, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """ADMIN_AUTHZ_FAIL_OPEN=true → silent fail-OPEN (legacy behavior для dev_light)."""
        monkeypatch.setenv("ADMIN_AUTHZ_FAIL_OPEN", "true")

        # Не должен raise — silently allow
        await admin_service_no_authz._authorize(
            actor="test_user",
            resource="admin.feature_flag:write",
            action="execute",
        )

    @pytest.mark.asyncio
    async def test_fail_open_with_env_value_1(
        self, admin_service_no_authz: AdminService, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """ADMIN_AUTHZ_FAIL_OPEN=1 (numeric) тоже активирует fail-OPEN."""
        monkeypatch.setenv("ADMIN_AUTHZ_FAIL_OPEN", "1")

        await admin_service_no_authz._authorize(
            actor="test_user",
            resource="admin.feature_flag:write",
            action="execute",
        )

    @pytest.mark.asyncio
    async def test_fail_open_env_false_does_not_activate(
        self, admin_service_no_authz: AdminService, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """ADMIN_AUTHZ_FAIL_OPEN=false (explicit OFF) → fail-CLOSED."""
        monkeypatch.setenv("ADMIN_AUTHZ_FAIL_OPEN", "false")

        with pytest.raises(AdminAuthorizationError):
            await admin_service_no_authz._authorize(
                actor="test_user",
                resource="admin.feature_flag:write",
                action="execute",
            )

    @pytest.mark.asyncio
    async def test_authorize_succeeds_when_authz_available(
        self, monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """AuthZ available + allow → succeed (нормальный happy path)."""
        svc = AdminService()

        # Mock AuthZ с разрешающим decision
        mock_authz = MagicMock()
        mock_decision = MagicMock()
        mock_decision.allowed = True
        mock_decision.reasons = []

        async def mock_authorize(**_kwargs: object) -> MagicMock:
            return mock_decision

        mock_authz.authorize = mock_authorize
        svc._authz = mock_authz

        monkeypatch.delenv("ADMIN_AUTHZ_FAIL_OPEN", raising=False)

        await svc._authorize(
            actor="test_user",
            resource="admin.feature_flag:write",
            action="execute",
        )
