"""D-AUDIT-9101: regression-тест mobile demo-auth fail-closed gate (API-P0-005).

Бывший баг: _verify_mobile_token в entrypoints/api/mobile/router.py
принимал ЛЮБОЙ bearer token формата 'mobile:<user_id>:<token>' без
валидации. Production: любой мог залогиниться от имени user_<...>.

Фикс (cycle 91): feature flag ``mobile_demo_auth_enabled`` (default
False в core/config/features/infrastructure.py). В production
(flag OFF) ЛЮБОЙ mobile:* токен → 401. В dev_light (flag ON) — старое
поведение для удобства разработки.
"""

from __future__ import annotations

import pytest
from fastapi import HTTPException

from src.backend.entrypoints.api.mobile import router as mobile_router


@pytest.mark.asyncio
async def test_demo_auth_disabled_returns_401(monkeypatch: pytest.MonkeyPatch) -> None:
    """Production (flag OFF) — 401 на любой mobile:* токен."""
    # Мокаем feature_flags так, чтобы mobile_demo_auth_enabled = False
    class _Flags:
        mobile_demo_auth_enabled = False

    import src.backend.core.config.features as features_mod

    monkeypatch.setattr(features_mod, "feature_flags", _Flags())

    with pytest.raises(HTTPException) as exc_info:
        await mobile_router._verify_mobile_token("Bearer mobile:user_xyz:abc123")
    assert exc_info.value.status_code == 401
    assert "Mobile auth disabled" in str(exc_info.value.detail)


@pytest.mark.asyncio
async def test_no_auth_header_returns_401() -> None:
    """Нет Authorization header → 401 (независимо от флага)."""
    with pytest.raises(HTTPException) as exc_info:
        await mobile_router._verify_mobile_token(None)
    assert exc_info.value.status_code == 401


@pytest.mark.asyncio
async def test_non_bearer_returns_401() -> None:
    """Не-Bearer схема → 401."""
    with pytest.raises(HTTPException) as exc_info:
        await mobile_router._verify_mobile_token("Basic dXNlcjpwYXNz")
    assert exc_info.value.status_code == 401


@pytest.mark.asyncio
async def test_demo_auth_enabled_accepts_mobile_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """dev_light (flag ON) — mobile:<user>:<token> принимается, user_id возвращается."""
    class _Flags:
        mobile_demo_auth_enabled = True

    import src.backend.core.config.features as features_mod

    monkeypatch.setattr(features_mod, "feature_flags", _Flags())

    user_id = await mobile_router._verify_mobile_token("Bearer mobile:user_xyz:abc123")
    assert user_id == "user_xyz"


@pytest.mark.asyncio
async def test_demo_auth_enabled_malformed_returns_401(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """dev_light (flag ON), но token не формата mobile:<user>:<token> → 401."""
    class _Flags:
        mobile_demo_auth_enabled = True

    import src.backend.core.config.features as features_mod

    monkeypatch.setattr(features_mod, "feature_flags", _Flags())

    with pytest.raises(HTTPException) as exc_info:
        await mobile_router._verify_mobile_token("Bearer mobile:just_one_part")
    assert exc_info.value.status_code == 401


@pytest.mark.asyncio
async def test_feature_flags_unavailable_fails_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Если feature_flags module недоступен (ImportError) → fail-CLOSED."""
    def _raise(*args: object, **kwargs: object) -> object:
        raise ImportError("simulated missing feature_flags")

    import src.backend.core.config.features as features_mod

    monkeypatch.setattr(features_mod, "feature_flags", property(_raise))

    with pytest.raises(HTTPException) as exc_info:
        await mobile_router._verify_mobile_token("Bearer mobile:user_xyz:abc123")
    assert exc_info.value.status_code == 401
