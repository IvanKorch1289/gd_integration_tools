"""Unit-тесты :class:`JwtBackend` (joserfc).

Покрытие:
* HS256 happy-path + неверный issuer/audience → JwtVerificationError;
* expired (exp в прошлом) → JwtVerificationError;
* RS256 через моделирование JWKS-кеша;
* blacklist по jti → JwtVerificationError;
* алгоритм не в whitelist → JwtVerificationError;
* отсутствие Authorization header → ``verify`` возвращает ``None``;
* malformed token → ``verify`` возвращает ``None`` (info-log).
"""

from __future__ import annotations

import time
from typing import Any

import pytest
from joserfc import jwt as joserfc_jwt
from joserfc.jwk import OctKey, RSAKey

from src.backend.core.auth.jwt_backend import (
    JwtBackend,
    JwtVerificationError,
    _parse_header_unsafe,
)

HS_SECRET = "supersecretkeywithatleast32characters!!"
ISS = "test-iss"
AUD = "test-aud"


def _make_hs_token(
    claims: dict[str, Any], *, alg: str = "HS256", secret: str = HS_SECRET
) -> str:
    key = OctKey.import_key(secret)
    return joserfc_jwt.encode({"alg": alg}, claims, key)


@pytest.fixture
def base_claims() -> dict[str, Any]:
    return {
        "sub": "user-1",
        "iss": ISS,
        "aud": AUD,
        "exp": int(time.time()) + 3600,
        "jti": "jti-1",
    }


@pytest.fixture
def hs_backend() -> JwtBackend:
    return JwtBackend(algorithms=["HS256"], secret=HS_SECRET, issuer=ISS, audience=AUD)


class _FakeRequest:
    def __init__(self, headers: dict[str, str] | None = None) -> None:
        self.headers = headers or {}


@pytest.mark.asyncio
async def test_hs256_happy_path(
    hs_backend: JwtBackend, base_claims: dict[str, Any]
) -> None:
    token = _make_hs_token(base_claims)
    claims = await hs_backend.decode(token)
    assert claims.sub == "user-1"
    assert claims.iss == ISS
    assert claims.aud == AUD
    assert claims.jti == "jti-1"


@pytest.mark.asyncio
async def test_hs256_wrong_issuer_rejected(
    hs_backend: JwtBackend, base_claims: dict[str, Any]
) -> None:
    base_claims["iss"] = "evil"
    token = _make_hs_token(base_claims)
    with pytest.raises(JwtVerificationError):
        await hs_backend.decode(token)


@pytest.mark.asyncio
async def test_hs256_wrong_audience_rejected(
    hs_backend: JwtBackend, base_claims: dict[str, Any]
) -> None:
    base_claims["aud"] = "evil"
    token = _make_hs_token(base_claims)
    with pytest.raises(JwtVerificationError):
        await hs_backend.decode(token)


@pytest.mark.asyncio
async def test_hs256_expired_rejected(
    hs_backend: JwtBackend, base_claims: dict[str, Any]
) -> None:
    base_claims["exp"] = int(time.time()) - 7200  # 2 часа назад
    token = _make_hs_token(base_claims)
    with pytest.raises(JwtVerificationError, match="истёк|claim|exp"):
        await hs_backend.decode(token)


@pytest.mark.asyncio
async def test_algorithm_not_in_whitelist_rejected(base_claims: dict[str, Any]) -> None:
    """Backend whitelist'ит только HS384; токен HS256 должен быть отвергнут."""
    backend = JwtBackend(
        algorithms=["HS384"], secret=HS_SECRET, issuer=ISS, audience=AUD
    )
    token = _make_hs_token(base_claims, alg="HS256")
    with pytest.raises(JwtVerificationError, match="HS256"):
        await backend.decode(token)


@pytest.mark.asyncio
async def test_wrong_signature_rejected(
    hs_backend: JwtBackend, base_claims: dict[str, Any]
) -> None:
    token = _make_hs_token(base_claims, secret="differentsecret-32-chars-long-aaaa")
    with pytest.raises(JwtVerificationError):
        await hs_backend.decode(token)


@pytest.mark.asyncio
async def test_blacklisted_jti_rejected(base_claims: dict[str, Any]) -> None:
    class FakeBlacklist:
        async def is_revoked(self, jti: str) -> bool:
            return jti == "jti-1"

    backend = JwtBackend(
        algorithms=["HS256"],
        secret=HS_SECRET,
        issuer=ISS,
        audience=AUD,
        blacklist=FakeBlacklist(),
    )
    token = _make_hs_token(base_claims)
    with pytest.raises(JwtVerificationError, match="отозван"):
        await backend.decode(token)


@pytest.mark.asyncio
async def test_jwks_rotation_revoke_before_time_scenario() -> None:
    """S18 W4 (S-L8-5): integration rotation scenario.

    Шаги:
        1. Issue токен с iat=100 (старый).
        2. blacklist.revoke_before_time(150) — barrier rotation.
        3. backend.decode(old_token) → JwtVerificationError ("rotation").
        4. Issue новый токен с iat=200.
        5. backend.decode(new_token) → succeeds.
        6. Per-jti revoke остаётся ортогональным:
           blacklist.revoke("jti-new", exp) → старая семантика работает.
    """

    class _RotationBlacklist:
        """In-memory blacklist с полным контрактом JwtBlacklistProtocol."""

        def __init__(self) -> None:
            self.per_jti: set[str] = set()
            self.revoke_before: int | None = None

        async def is_revoked(self, jti: str) -> bool:
            return jti in self.per_jti

        async def revoke(self, jti: str, expires_at: int) -> None:
            self.per_jti.add(jti)

        async def revoke_before_time(self, time_threshold: int) -> None:
            current = self.revoke_before or 0
            self.revoke_before = max(current, int(time_threshold))

        async def is_iat_revoked(self, iat: int | None) -> bool:
            if iat is None or self.revoke_before is None:
                return False
            return int(iat) < self.revoke_before

    blacklist = _RotationBlacklist()
    backend = JwtBackend(
        algorithms=["HS256"],
        secret=HS_SECRET,
        issuer=ISS,
        audience=AUD,
        blacklist=blacklist,
    )

    # 1. Старый токен (iat=100)
    now_unix = int(time.time())
    old_claims: dict[str, Any] = {
        "sub": "user-1",
        "iss": ISS,
        "aud": AUD,
        "exp": now_unix + 3600,
        "iat": 100,
        "jti": "jti-old",
    }
    old_token = _make_hs_token(old_claims)

    # До rotation — старый токен валиден
    claims_before = await backend.decode(old_token)
    assert claims_before.sub == "user-1"

    # 2. Rotation barrier на t=150
    await blacklist.revoke_before_time(150)

    # 3. Старый токен теперь отозван (iat=100 < 150)
    with pytest.raises(JwtVerificationError, match="rotation"):
        await backend.decode(old_token)

    # 4. Новый токен с iat=200 (после barrier)
    new_claims: dict[str, Any] = {
        "sub": "user-2",
        "iss": ISS,
        "aud": AUD,
        "exp": now_unix + 3600,
        "iat": 200,
        "jti": "jti-new",
    }
    new_token = _make_hs_token(new_claims)
    # 5. Новый токен — успешно валидируется
    claims_after = await backend.decode(new_token)
    assert claims_after.sub == "user-2"

    # 6. Per-jti revoke остаётся ортогональным batch-revoke
    await blacklist.revoke("jti-new", expires_at=now_unix + 3600)
    with pytest.raises(JwtVerificationError, match="blacklist"):
        await backend.decode(new_token)


@pytest.mark.asyncio
async def test_verify_returns_none_without_authorization_header(
    hs_backend: JwtBackend,
) -> None:
    ctx = await hs_backend.verify(_FakeRequest())
    assert ctx is None


@pytest.mark.asyncio
async def test_verify_returns_none_for_non_bearer(hs_backend: JwtBackend) -> None:
    ctx = await hs_backend.verify(_FakeRequest({"Authorization": "Basic abc"}))
    assert ctx is None


@pytest.mark.asyncio
async def test_verify_returns_none_for_malformed_token(hs_backend: JwtBackend) -> None:
    ctx = await hs_backend.verify(_FakeRequest({"Authorization": "Bearer not-a-jwt"}))
    assert ctx is None


@pytest.mark.asyncio
async def test_verify_success_returns_auth_context(
    hs_backend: JwtBackend, base_claims: dict[str, Any]
) -> None:
    token = _make_hs_token(base_claims)
    ctx = await hs_backend.verify(_FakeRequest({"Authorization": f"Bearer {token}"}))
    assert ctx is not None
    assert ctx.principal == "user-1"
    assert ctx.method.value == "jwt"


@pytest.mark.asyncio
async def test_rs256_via_jwks_cache(base_claims: dict[str, Any]) -> None:
    rsa_key = RSAKey.generate_key(2048, parameters={"kid": "kid-1", "use": "sig"})
    jwks_dict = {"keys": [rsa_key.as_dict()]}

    class FakeJwks:
        url = "https://idp.example/.well-known/jwks.json"

        async def get_keys(self) -> dict[str, Any]:
            return jwks_dict

        async def get_key(self, kid: str) -> dict[str, Any] | None:
            for k in jwks_dict["keys"]:
                if k.get("kid") == kid:
                    return k
            return None

    backend = JwtBackend(
        algorithms=["RS256"],
        jwks=FakeJwks(),  # type: ignore[arg-type]
        issuer=ISS,
        audience=AUD,
    )
    token = joserfc_jwt.encode({"alg": "RS256", "kid": "kid-1"}, base_claims, rsa_key)
    claims = await backend.decode(token)
    assert claims.sub == "user-1"


@pytest.mark.asyncio
async def test_rs256_missing_kid_rejected(base_claims: dict[str, Any]) -> None:
    rsa_key = RSAKey.generate_key(2048, parameters={"kid": "kid-1", "use": "sig"})

    class FakeJwks:
        url = ""

        async def get_keys(self) -> dict[str, Any]:
            return {"keys": [rsa_key.as_dict()]}

        async def get_key(self, kid: str) -> dict[str, Any] | None:
            return None

    backend = JwtBackend(
        algorithms=["RS256"],
        jwks=FakeJwks(),  # type: ignore[arg-type]
    )
    token = joserfc_jwt.encode({"alg": "RS256"}, base_claims, rsa_key)
    with pytest.raises(JwtVerificationError, match="kid"):
        await backend.decode(token)


def test_constructor_rejects_empty_algorithms() -> None:
    with pytest.raises(ValueError, match="algorithms"):
        JwtBackend(algorithms=[], secret=HS_SECRET)


def test_constructor_requires_secret_for_symmetric() -> None:
    with pytest.raises(ValueError, match="secret"):
        JwtBackend(algorithms=["HS256"], secret=None)


def test_constructor_requires_jwks_for_asymmetric() -> None:
    with pytest.raises(ValueError, match="jwks"):
        JwtBackend(algorithms=["RS256"])


def test_constructor_rejects_unknown_algorithm() -> None:
    with pytest.raises(ValueError, match="неподдерживаемый"):
        JwtBackend(algorithms=["XX999"], secret=HS_SECRET)


def test_parse_header_unsafe_extracts_alg_and_kid() -> None:
    rsa_key = RSAKey.generate_key(2048, parameters={"kid": "kid-x"})
    token = joserfc_jwt.encode({"alg": "RS256", "kid": "kid-x"}, {"sub": "u"}, rsa_key)
    header = _parse_header_unsafe(token)
    assert header["alg"] == "RS256"
    assert header["kid"] == "kid-x"


def test_parse_header_unsafe_invalid_token() -> None:
    with pytest.raises(JwtVerificationError, match="header"):
        _parse_header_unsafe("not-a-jwt")
