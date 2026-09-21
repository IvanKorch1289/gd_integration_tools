"""Unit tests for NoOpBillingFacade + DI provider (cycle 33, B-07).

Тесты покрывают:

* структурную совместимость :class:`NoOpBillingFacade` с
  :class:`QuotasBackend` Protocol;
* поведение ``consume_request`` / ``check_tokens`` (allowed=True,
  reason='billing_not_configured', нулевые счётчики);
* эмиссию audit-event ``quota_check_skipped`` через singleton
  :class:`AuditService` (mock на границе сервиса, не на функции-под-тестом);
* DI-провайдер: default = NoOpBillingFacade, override через
  ``set_quotas_backend_provider``, ``BILLING_ENABLED=True`` →
  ``NotImplementedError``;
* stub-скелет :class:`QuotasService`` бросает ``NotImplementedError``.

Audit-facade mockится на уровне singleton'а
(:func:`get_unified_audit_service`), не на уровне внутренней
``_emit_quota_check_skipped`` — последняя сама оборачивает ошибки в
WARNING-лог и не должна ломать consume_request.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from src.backend.core.auth.quotas_protocol import (
    QuotaCheckResult,
    QuotasBackend,
    QuotaUsage,
)
from src.backend.services.billing import BILLING_ENABLED, NoOpBillingFacade


class TestNoOpBillingFacadeStructural:
    """``NoOpBillingFacade`` структурно реализует :class:`QuotasBackend`."""

    def test_isinstance_protocol(self) -> None:
        # Runtime-checkable Protocol: isinstance должен пройти без monkey-patch.
        assert isinstance(NoOpBillingFacade(), QuotasBackend)

    def test_consume_request_signature(self) -> None:
        import inspect

        sig = inspect.signature(NoOpBillingFacade.consume_request)
        params = list(sig.parameters.keys())
        assert params[0] == "self"
        assert "tenant_id" in params

    def test_check_tokens_signature(self) -> None:
        import inspect

        sig = inspect.signature(NoOpBillingFacade.check_tokens)
        params = list(sig.parameters.keys())
        assert params[0] == "self"
        assert "tenant_id" in params
        assert "tokens" in params


class TestNoOpBillingFacadeBehavior:
    """Поведение no-op фасада: allowed=True, reason='billing_not_configured'."""

    @pytest.mark.asyncio
    async def test_consume_request_returns_allowed_true(self) -> None:
        facade = NoOpBillingFacade()
        # Mock AuditService чтобы не зависеть от ClickHouse backend.
        with patch(
            "src.backend.core.audit.facade.audit_service.get_unified_audit_service",
            return_value=_make_audit_mock(),
        ):
            result = await facade.consume_request("tenant-1")

        assert isinstance(result, QuotaCheckResult)
        assert result.allowed is True
        assert result.reason == "billing_not_configured"
        assert isinstance(result.usage, QuotaUsage)
        assert result.usage.tenant_id == "tenant-1"
        assert result.usage.requests_in_minute == 0
        assert result.usage.requests_in_day == 0

    @pytest.mark.asyncio
    async def test_check_tokens_returns_allowed_true(self) -> None:
        facade = NoOpBillingFacade()
        with patch(
            "src.backend.core.audit.facade.audit_service.get_unified_audit_service",
            return_value=_make_audit_mock(),
        ):
            result = await facade.check_tokens("tenant-2", tokens=500)

        assert result.allowed is True
        assert result.reason == "billing_not_configured"
        assert result.usage.tenant_id == "tenant-2"

    @pytest.mark.asyncio
    async def test_audit_event_emitted(self) -> None:
        audit_mock = _make_audit_mock()
        facade = NoOpBillingFacade()
        with patch(
            "src.backend.core.audit.facade.audit_service.get_unified_audit_service",
            return_value=audit_mock,
        ):
            await facade.consume_request("tenant-3")

        audit_mock.emit.assert_awaited_once()
        call_kwargs = audit_mock.emit.await_args.kwargs
        assert call_kwargs["event"] == "quota_check_skipped"
        assert call_kwargs["actor"] == "system"
        assert call_kwargs["resource"] == "tenant/tenant-3"
        assert call_kwargs["action"] == "quota_check"
        assert call_kwargs["outcome"] == "success"
        assert call_kwargs["severity"] == "info"
        assert call_kwargs["tenant_id"] == "tenant-3"
        assert call_kwargs["details"]["facade"] == "no_op"
        assert call_kwargs["details"]["method"] == "consume_request"
        assert call_kwargs["details"]["reason"] == "billing_not_configured"

    @pytest.mark.asyncio
    async def test_check_tokens_emits_audit_with_tokens(self) -> None:
        audit_mock = _make_audit_mock()
        facade = NoOpBillingFacade()
        with patch(
            "src.backend.core.audit.facade.audit_service.get_unified_audit_service",
            return_value=audit_mock,
        ):
            await facade.check_tokens("tenant-4", tokens=42)

        audit_mock.emit.assert_awaited_once()
        details = audit_mock.emit.await_args.kwargs["details"]
        assert details["tokens"] == 42
        assert details["method"] == "check_tokens"

    @pytest.mark.asyncio
    async def test_audit_failure_does_not_break_consume(self) -> None:
        # Если audit backend падает — consume_request всё равно возвращает OK.
        audit_mock = _make_audit_mock()
        audit_mock.emit = AsyncMock(side_effect=RuntimeError("clickhouse down"))
        facade = NoOpBillingFacade()
        with patch(
            "src.backend.core.audit.facade.audit_service.get_unified_audit_service",
            return_value=audit_mock,
        ):
            result = await facade.consume_request("tenant-5")
        assert result.allowed is True

    @pytest.mark.asyncio
    async def test_audit_resolver_failure_does_not_break_consume(self) -> None:
        # Если get_unified_audit_service падает — фасад НЕ должен raise.
        facade = NoOpBillingFacade()
        with patch(
            "src.backend.core.audit.facade.audit_service.get_unified_audit_service",
            side_effect=RuntimeError("DI broken"),
        ):
            result = await facade.consume_request("tenant-6")
        assert result.allowed is True


class TestNoOpBillingFacadeRejectsWhenBillingEnabled:
    """``BILLING_ENABLED=True`` → :class:`NotImplementedError`."""

    @pytest.mark.asyncio
    async def test_consume_request_raises_when_enabled(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from src.backend.services.billing import no_op_billing

        monkeypatch.setattr(no_op_billing, "BILLING_ENABLED", True)
        facade = NoOpBillingFacade()
        with pytest.raises(NotImplementedError, match="billing_enabled=True"):
            await facade.consume_request("tenant-1")

    @pytest.mark.asyncio
    async def test_check_tokens_raises_when_enabled(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from src.backend.services.billing import no_op_billing

        monkeypatch.setattr(no_op_billing, "BILLING_ENABLED", True)
        facade = NoOpBillingFacade()
        with pytest.raises(NotImplementedError, match="billing_enabled=True"):
            await facade.check_tokens("tenant-1", tokens=10)


class TestBillingPackageExports:
    """Пакетный ``__init__`` re-export'ит public API."""

    def test_package_reexports_no_op_billing_facade(self) -> None:
        from src.backend.services.billing import NoOpBillingFacade as Imported

        assert Imported is NoOpBillingFacade

    def test_package_reexports_billing_enabled_flag(self) -> None:
        from src.backend.services.billing import BILLING_ENABLED as Imported

        assert Imported is BILLING_ENABLED

    def test_package_reexports_quotas_service_stub(self) -> None:
        from src.backend.services.billing import QuotasService

        assert QuotasService.__name__ == "QuotasService"

    def test_default_billing_enabled_is_false(self) -> None:
        # Защита от случайного ON: default должен быть False.
        assert BILLING_ENABLED is False


class TestQuotasServiceStub:
    """Stub :class:`QuotasService` бросает ``NotImplementedError``."""

    def test_init_raises(self) -> None:
        from src.backend.services.billing.quotas_service import QuotasService

        with pytest.raises(NotImplementedError, match="QuotasService not yet"):
            QuotasService()


class TestBillingProvider:
    """DI-провайдер ``core.di.providers.billing``."""

    def test_default_returns_no_op_billing_facade(self) -> None:
        from src.backend.core.di.providers import billing

        billing.set_quotas_backend_provider(None)  # reset override
        provider = billing.get_quotas_backend_provider()
        assert isinstance(provider, NoOpBillingFacade)

    def test_override_takes_precedence(self) -> None:
        from src.backend.core.di.providers import billing

        custom = MagicMock(spec=QuotasBackend, name="custom_quota")
        billing.set_quotas_backend_provider(custom)
        try:
            assert billing.get_quotas_backend_provider() is custom
        finally:
            billing.set_quotas_backend_provider(None)

    def test_set_none_resets_override(self) -> None:
        from src.backend.core.di.providers import billing

        custom = MagicMock(spec=QuotasBackend, name="custom_quota_v2")
        billing.set_quotas_backend_provider(custom)
        billing.set_quotas_backend_provider(None)
        provider = billing.get_quotas_backend_provider()
        assert isinstance(provider, NoOpBillingFacade)

    def test_billing_enabled_raises_not_implemented(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from src.backend.core.di.providers import billing
        from src.backend.services.billing import no_op_billing

        billing.set_quotas_backend_provider(None)
        monkeypatch.setattr(no_op_billing, "BILLING_ENABLED", True)
        with pytest.raises(NotImplementedError, match="billing_enabled=True"):
            billing.get_quotas_backend_provider()
        # Сброс флага, чтобы не аффектить другие тесты.
        monkeypatch.setattr(no_op_billing, "BILLING_ENABLED", False)

    def test_provider_overrides_isolated_from_ai(self) -> None:
        # Проверяем, что overrides в billing.py не утекают в другие провайдеры.
        from src.backend.core.di.providers import ai, billing

        billing.set_quotas_backend_provider(MagicMock(name="B"))
        ai.set_ai_sanitizer_provider(MagicMock(name="A"))
        assert isinstance(billing.get_quotas_backend_provider(), MagicMock)
        assert ai.get_ai_sanitizer_provider()._mock_name == "A"
        billing.set_quotas_backend_provider(None)


# ─────────────────────── helpers ───────────────────────


def _make_audit_mock() -> MagicMock:
    """Возвращает MagicMock, имитирующий :class:`AuditService` с async emit."""
    mock = MagicMock(name="audit_service")
    mock.emit = AsyncMock(return_value=None)
    return mock


@pytest.fixture(autouse=True)
def _reset_provider_overrides() -> Any:
    """Сбрасывает overrides до/после каждого теста (изоляция)."""
    from src.backend.core.di.providers import billing

    billing.set_quotas_backend_provider(None)
    yield
    billing.set_quotas_backend_provider(None)
