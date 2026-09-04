"""C2 (ledger 2026-09-04): тесты wiring mobile JWT protections.

Флаг ``mobile_jwt_protections_enabled`` управляет сборкой verifier'а:
- True  → ``build_verifier_with_protections`` с Redis-backed stores
          (M1-#22 protections перестают быть мёртвым кодом);
- False → bare ``MobileJwtVerifier`` (историческое поведение).
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from tests.unit.entrypoints.api.mobile.test_mobile_router_jwt_integration import (
    _build_client_with_flags,
)

_FACTORY_TARGET = "src.backend.core.auth.mobile_jwt_revocation.build_verifier_with_protections"


def test_protections_flag_on_builds_verifier_with_stores() -> None:
    """Флаг ON → factory вызывается с revocation_store и rate_limiter."""
    for client, _ in _build_client_with_flags(
        mobile_jwt_enabled=True,
        mobile_jwt_protections_enabled=True,
    ):
        mock_ctx = SimpleNamespace(
            user_id="u1",
            device_id="11111111-2222-4333-8444-555555555555",
            jti="jti-1",
            tenant_id="t1",
        )
        mock_verifier = AsyncMock()
        mock_verifier.verify = AsyncMock(return_value=mock_ctx)

        with patch(_FACTORY_TARGET, return_value=mock_verifier) as mock_factory:
            with patch("src.backend.core.auth.jwt_backend.JwtBackend"):
                response = client.get(
                    "/mobile/v1/profile",
                    headers={"Authorization": "Bearer valid.jwt.token"},
                )

        assert response.status_code == 200
        mock_factory.assert_called_once()
        kwargs = mock_factory.call_args.kwargs
        assert kwargs["revocation_store"] is not None
        assert kwargs["rate_limiter"] is not None


def test_protections_flag_off_keeps_bare_verifier() -> None:
    """Флаг OFF → factory НЕ вызывается (bare MobileJwtVerifier путь)."""
    for client, _ in _build_client_with_flags(
        mobile_jwt_enabled=True,
        mobile_jwt_protections_enabled=False,
    ):
        valid_claims = {
            "iss": "gd-mobile-prod",
            "aud": "gd-mobile-api",
            "sub": "user_x",
            "device_id": "11111111-2222-4333-8444-555555555555",
            "tenant_id": "t1",
            "jti": "jti-2",
        }

        with patch(_FACTORY_TARGET) as mock_factory:
            with patch(
                "src.backend.core.auth.jwt_backend.JwtBackend"
            ) as mock_backend_cls:
                mock_backend = AsyncMock()
                mock_backend.decode = AsyncMock(return_value=valid_claims)
                mock_backend_cls.return_value = mock_backend

                response = client.get(
                    "/mobile/v1/profile",
                    headers={"Authorization": "Bearer valid.jwt.token"},
                )

        assert response.status_code == 200
        mock_factory.assert_not_called()


# ── C2-review P1 fix: limiter decision обязана отклонять ──────────


def _jwt_error():
    from src.backend.core.auth.jwt_backend import JwtVerificationError

    return JwtVerificationError


async def _verify_with_limiter(limiter) -> None:
    """Прогнать wrapped verifier с заданным limiter (ожидаем rejection)."""
    from src.backend.core.auth.mobile_jwt_revocation import _WrappedMobileJwtVerifier

    inner = AsyncMock()
    inner.verify = AsyncMock(
        return_value=SimpleNamespace(
            user_id="u",
            device_id="11111111-2222-4333-8444-555555555555",
            jti="j",
        )
    )
    wrapper = _WrappedMobileJwtVerifier(
        inner=inner, revocation_store=None, rate_limiter=limiter
    )
    with pytest.raises(_jwt_error(), match="rate limit exceeded"):
        await wrapper.verify("token")


@pytest.mark.asyncio
async def test_rate_limit_decision_object_rejects() -> None:
    """DeviceRateLimiter-контракт: RateLimitDecision(allowed=False) → reject."""
    limiter = AsyncMock()
    limiter.check = AsyncMock(
        return_value=SimpleNamespace(allowed=False, remaining=0, reset_seconds=1.0)
    )
    await _verify_with_limiter(limiter)


@pytest.mark.asyncio
async def test_rate_limit_tuple_contract_rejects() -> None:
    """RedisRateLimiter-контракт: (False, 0) → reject."""
    limiter = AsyncMock()
    limiter.check = AsyncMock(return_value=(False, 0))
    await _verify_with_limiter(limiter)


@pytest.mark.asyncio
async def test_rate_limit_allowed_passes() -> None:
    """allowed=True → запрос проходит (rejection не срабатывает)."""
    from src.backend.core.auth.mobile_jwt_revocation import _WrappedMobileJwtVerifier

    inner = AsyncMock()
    ctx = SimpleNamespace(
        user_id="u", device_id="d", jti="j"
    )
    inner.verify = AsyncMock(return_value=ctx)
    limiter = AsyncMock()
    limiter.check = AsyncMock(return_value=(True, 5))
    wrapper = _WrappedMobileJwtVerifier(
        inner=inner, revocation_store=None, rate_limiter=limiter
    )
    result = await wrapper.verify("token")
    assert result is ctx
