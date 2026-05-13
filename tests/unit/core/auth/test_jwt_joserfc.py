"""Unit-тесты parallel shim ``jwt_backend_joserfc`` и feature-flag dispatch.

Wave [s2/k1-w1-joserfc] — K1 Sprint-2 Wave 1.

Покрытие:
* Прямой импорт jwt_backend_joserfc без крэша;
* encode/decode через shim-модуль (HS256 happy-path);
* JwtBackend из shim: decode + verify (flag ON через monkey-patch);
* Feature-flag OFF: jwt_backend.JwtBackend использует внутреннюю joserfc-реализацию;
* Feature-flag ON: jwt_backend.JwtBackend делегирует в shim;
* Cross-decode: токен, созданный через shim encode → декодируется
  основным jwt_backend.JwtBackend.decode (claims совпадают);
* Cross-decode обратный: токен из jwt_backend._make_hs_token (OctKey)
  → shim.decode → равные claims.
"""

from __future__ import annotations

import sys
import time
from contextlib import contextmanager
from typing import Any, Generator

import pytest
from joserfc.jwk import OctKey

import src.backend.core.auth.jwt_backend_joserfc as joserfc_shim
from src.backend.core.auth.jwt_backend import JwtBackend as MainJwtBackend
from src.backend.core.auth.jwt_backend import JwtClaims as MainJwtClaims
from src.backend.core.auth.jwt_backend_joserfc import JwtBackend as ShimJwtBackend
from src.backend.core.auth.jwt_backend_joserfc import JwtVerificationError, encode

HS_SECRET = "supersecretkeywithatleast32characters!!"
ISS = "joserfc-test-iss"
AUD = "joserfc-test-aud"

_FEATURES_MODULE_KEY = "src.backend.core.config.features"


@contextmanager
def _patch_auth_joserfc(value: bool) -> Generator[None, None, None]:
    """Временно подменяет feature_flags.auth_joserfc в уже загруженном модуле.

    Загружает модуль features через importlib при необходимости, чтобы
    он был в sys.modules перед monkey-patch.
    """
    import importlib

    if _FEATURES_MODULE_KEY not in sys.modules:
        # Модуль ещё не загружен — принудительно загружаем
        importlib.import_module(_FEATURES_MODULE_KEY)

    ff_mod = sys.modules[_FEATURES_MODULE_KEY]
    orig = ff_mod.feature_flags  # type: ignore[attr-defined]
    ff_mod.feature_flags = type("FF", (), {"auth_joserfc": value})()  # type: ignore[assignment]
    try:
        yield
    finally:
        ff_mod.feature_flags = orig  # type: ignore[assignment]


def _base_claims() -> dict[str, Any]:
    """Возвращает базовые claims с живым exp."""
    return {
        "sub": "user-joserfc",
        "iss": ISS,
        "aud": AUD,
        "exp": int(time.time()) + 3600,
        "jti": "jti-joserfc-1",
    }


def _make_shim_token(claims: dict[str, Any]) -> str:
    """Создаёт HS256 токен через shim encode."""
    return encode(claims, alg="HS256", secret=HS_SECRET)


def _make_main_token(claims: dict[str, Any]) -> str:
    """Создаёт HS256 токен через joserfc_jwt напрямую (имитирует old-path)."""
    from joserfc import jwt as joserfc_jwt

    key = OctKey.import_key(HS_SECRET)
    return joserfc_jwt.encode({"alg": "HS256"}, claims, key)


# ─── 1. Smoke import ──────────────────────────────────────────────────────────

def test_shim_module_importable() -> None:
    """Модуль jwt_backend_joserfc импортируется без ошибок."""
    assert hasattr(joserfc_shim, "JwtBackend")
    assert hasattr(joserfc_shim, "JwtVerificationError")
    assert hasattr(joserfc_shim, "JwtClaims")
    assert hasattr(joserfc_shim, "encode")
    assert hasattr(joserfc_shim, "decode")


# ─── 2. encode / decode standalone ──────────────────────────────────────────

def test_shim_encode_decode_hs256() -> None:
    """encode → decode через shim: claims совпадают."""
    claims = _base_claims()
    token = _make_shim_token(claims)
    decoded = joserfc_shim.decode(
        token, algorithms=["HS256"], secret=HS_SECRET
    )
    assert decoded["sub"] == "user-joserfc"
    assert decoded["iss"] == ISS


def test_shim_encode_rejects_missing_secret() -> None:
    """encode без secret для HS поднимает ValueError."""
    with pytest.raises(ValueError, match="secret"):
        encode(_base_claims(), alg="HS256", secret=None)


def test_shim_encode_rejects_missing_private_key_for_rs256() -> None:
    """encode без private_key для RS256 поднимает ValueError."""
    with pytest.raises(ValueError, match="private_key"):
        encode(_base_claims(), alg="RS256", private_key=None)


def test_shim_decode_bad_signature_raises() -> None:
    """decode с другим секретом → JwtVerificationError."""
    token = encode(_base_claims(), alg="HS256", secret=HS_SECRET)
    with pytest.raises(JwtVerificationError):
        joserfc_shim.decode(
            token, algorithms=["HS256"], secret="wrong-secret-32-chars-long-xxxx"
        )


# ─── 3. ShimJwtBackend.decode + verify ───────────────────────────────────────

@pytest.fixture
def shim_backend() -> ShimJwtBackend:
    """ShimJwtBackend для HS256."""
    return ShimJwtBackend(
        algorithms=["HS256"],
        secret=HS_SECRET,
        issuer=ISS,
        audience=AUD,
    )


class _FakeRequest:
    def __init__(self, headers: dict[str, str] | None = None) -> None:
        self.headers = headers or {}


@pytest.mark.asyncio
async def test_shim_backend_decode_happy_path(shim_backend: ShimJwtBackend) -> None:
    """ShimJwtBackend.decode: happy-path HS256."""
    token = _make_shim_token(_base_claims())
    claims = await shim_backend.decode(token)
    assert claims.sub == "user-joserfc"
    assert claims.iss == ISS
    assert claims.aud == AUD
    assert claims.jti == "jti-joserfc-1"


@pytest.mark.asyncio
async def test_shim_backend_verify_success(shim_backend: ShimJwtBackend) -> None:
    """ShimJwtBackend.verify: возвращает AuthContext для valid Bearer."""
    token = _make_shim_token(_base_claims())
    ctx = await shim_backend.verify(_FakeRequest({"Authorization": f"Bearer {token}"}))
    assert ctx is not None
    assert ctx.principal == "user-joserfc"


@pytest.mark.asyncio
async def test_shim_backend_verify_none_without_header(
    shim_backend: ShimJwtBackend,
) -> None:
    """ShimJwtBackend.verify: None без Authorization."""
    ctx = await shim_backend.verify(_FakeRequest())
    assert ctx is None


# ─── 4. Feature-flag dispatch через jwt_backend.JwtBackend ───────────────────

@pytest.fixture
def main_backend() -> MainJwtBackend:
    """Основной MainJwtBackend для HS256."""
    return MainJwtBackend(
        algorithms=["HS256"],
        secret=HS_SECRET,
        issuer=ISS,
        audience=AUD,
    )


@pytest.mark.asyncio
async def test_main_backend_flag_off_uses_internal_path(
    main_backend: MainJwtBackend,
) -> None:
    """MainJwtBackend.decode с flag OFF: старая внутренняя логика, возвращает JwtClaims."""
    token = _make_main_token(_base_claims())
    with _patch_auth_joserfc(False):
        claims = await main_backend.decode(token)
    assert isinstance(claims, MainJwtClaims)
    assert claims.sub == "user-joserfc"


@pytest.mark.asyncio
async def test_main_backend_flag_on_delegates_to_shim(
    main_backend: MainJwtBackend,
) -> None:
    """MainJwtBackend.decode с flag ON: делегирует в shim, возвращает JwtClaims."""
    token = _make_shim_token(_base_claims())
    with _patch_auth_joserfc(True):
        claims = await main_backend.decode(token)
    assert isinstance(claims, MainJwtClaims)
    assert claims.sub == "user-joserfc"
    assert claims.iss == ISS


@pytest.mark.asyncio
async def test_main_backend_verify_flag_on_delegates_to_shim(
    main_backend: MainJwtBackend,
) -> None:
    """MainJwtBackend.verify с flag ON: делегирует в shim."""
    token = _make_shim_token(_base_claims())
    with _patch_auth_joserfc(True):
        ctx = await main_backend.verify(
            _FakeRequest({"Authorization": f"Bearer {token}"})
        )
    assert ctx is not None
    assert ctx.principal == "user-joserfc"


# ─── 5. Cross-decode ──────────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_cross_decode_shim_token_via_main_backend(
    main_backend: MainJwtBackend,
) -> None:
    """Токен от shim encode → MainJwtBackend.decode (flag OFF) → claims равны."""
    claims_in = _base_claims()
    token = _make_shim_token(claims_in)
    with _patch_auth_joserfc(False):
        claims_out = await main_backend.decode(token)
    assert claims_out.sub == claims_in["sub"]
    assert claims_out.iss == claims_in["iss"]
    assert claims_out.jti == claims_in["jti"]


@pytest.mark.asyncio
async def test_cross_decode_main_token_via_shim_backend(
    shim_backend: ShimJwtBackend,
) -> None:
    """Токен от main _make_main_token → ShimJwtBackend.decode → claims равны."""
    claims_in = _base_claims()
    token = _make_main_token(claims_in)
    claims_out = await shim_backend.decode(token)
    assert claims_out.sub == claims_in["sub"]
    assert claims_out.iss == claims_in["iss"]
    assert claims_out.jti == claims_in["jti"]


# ─── 6. Default flag OFF (интеграционная проверка) ────────────────────────────

def test_feature_flag_default_off() -> None:
    """feature_flags.auth_joserfc по умолчанию False."""
    import importlib

    ff_mod = importlib.import_module("src.backend.core.config.features")
    feature_flags = ff_mod.feature_flags  # type: ignore[attr-defined]

    assert feature_flags.auth_joserfc is False, (
        "feature_flags.auth_joserfc должен быть default-OFF (False). "
        "Переключение на True — отдельный PR после staging-smoke."
    )
