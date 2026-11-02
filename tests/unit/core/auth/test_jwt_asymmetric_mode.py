"""Unit-тесты асимметричного режима JWT (ADR-0411, RS256/ES256).

Покрытие:
* проверка RS256-токена по локальному PEM-публичному ключу (``public_key``);
* явный отказ: HS256-токен в RS256-режиме (нет «тихого» downgrade);
* algorithm confusion: HS256-токен, подписанный публичным ключом;
* JWKS-резолв по ``kid`` (заглушка) + отказ по неизвестному/отсутствующему kid;
* несоответствие типа ключа и алгоритма (EC-ключ под RS256);
* конструктор: нельзя смешивать HS* и RS*/ES*; нужен jwks или public_key;
* low-level ``jwt_backend.decode`` — отказ по алгоритму вне allowlist.
"""

from __future__ import annotations

import time
from typing import Any

import pytest
from joserfc import jwt as joserfc_jwt
from joserfc.jwk import ECKey, OctKey, RSAKey

from src.backend.core.auth.jwt_backend import JwtBackend, JwtVerificationError
from src.backend.core.auth.jwt_backend import decode as low_level_decode
from src.backend.core.auth.jwt_backend_helpers import _assert_key_matches_alg


def _rsa_key(kid: str = "kid-1") -> RSAKey:
    return RSAKey.generate_key(2048, parameters={"kid": kid, "use": "sig"})


def _ec_key(kid: str = "kid-ec") -> ECKey:
    return ECKey.generate_key("P-256", parameters={"kid": kid, "use": "sig"})


def _claims() -> dict[str, Any]:
    return {"sub": "user-1", "iat": int(time.time()), "exp": int(time.time()) + 3600}


def _rs256_token(key: RSAKey, *, kid: str | None = "kid-1") -> str:
    header: dict[str, Any] = {"alg": "RS256"}
    if kid is not None:
        header["kid"] = kid
    return joserfc_jwt.encode(header, _claims(), key)


def _hs256_token(secret: str) -> str:
    return joserfc_jwt.encode({"alg": "HS256"}, _claims(), OctKey.import_key(secret))


class TestAsymmetricVerification:
    """Проверка подписи по публичному ключу (PEM) и по JWKS."""

    @pytest.mark.asyncio
    async def test_rs256_verified_with_static_public_key(self) -> None:
        key = _rsa_key()
        backend = JwtBackend(algorithms=["RS256"], public_key=key)
        claims = await backend.decode(_rs256_token(key))
        assert claims.sub == "user-1"

    @pytest.mark.asyncio
    async def test_rs256_verified_via_jwks_kid(self) -> None:
        key = _rsa_key()
        jwks_dict = {"keys": [key.as_dict()]}

        class FakeJwks:
            url = "https://idp.example/.well-known/jwks.json"

            async def get_keys(self) -> dict[str, Any]:
                return jwks_dict

            async def get_key(self, kid: str) -> dict[str, Any] | None:
                for item in jwks_dict["keys"]:
                    if item.get("kid") == kid:
                        return item
                return None

        backend = JwtBackend(algorithms=["RS256"], jwks=FakeJwks())  # type: ignore[arg-type]
        claims = await backend.decode(_rs256_token(key))
        assert claims.sub == "user-1"

    @pytest.mark.asyncio
    async def test_jwks_unknown_kid_rejected(self) -> None:
        key = _rsa_key(kid="kid-1")

        class FakeJwks:
            url = "https://idp.example/.well-known/jwks.json"

            async def get_keys(self) -> dict[str, Any]:
                return {"keys": []}

            async def get_key(self, kid: str) -> dict[str, Any] | None:
                return None

        backend = JwtBackend(algorithms=["RS256"], jwks=FakeJwks())  # type: ignore[arg-type]
        with pytest.raises(JwtVerificationError, match="kid-1"):
            await backend.decode(_rs256_token(key))

    @pytest.mark.asyncio
    async def test_static_public_key_with_mismatched_kid_rejected(self) -> None:
        key = _rsa_key(kid="kid-1")
        backend = JwtBackend(algorithms=["RS256"], public_key=key, kid="kid-expected")
        with pytest.raises(JwtVerificationError, match="kid"):
            await backend.decode(_rs256_token(key, kid="kid-1"))

    @pytest.mark.asyncio
    async def test_static_public_key_accepts_token_without_kid(self) -> None:
        key = _rsa_key()
        backend = JwtBackend(algorithms=["RS256"], public_key=key)
        claims = await backend.decode(_rs256_token(key, kid=None))
        assert claims.sub == "user-1"


class TestAlgorithmMismatch:
    """Явный отказ при несоответствии алгоритма и ключа."""

    @pytest.mark.asyncio
    async def test_hs256_token_rejected_in_rs256_mode(self) -> None:
        backend = JwtBackend(algorithms=["RS256"], public_key=_rsa_key())
        with pytest.raises(JwtVerificationError, match="не разрешён"):
            await backend.decode(
                _hs256_token("supersecretkeywithatleast32characters!!")
            )

    @pytest.mark.asyncio
    async def test_algorithm_confusion_public_key_as_hmac_secret_rejected(self) -> None:
        """HS256-токен, подписанный публичным ключом, не принимается."""
        key = _rsa_key()
        backend = JwtBackend(algorithms=["RS256"], public_key=key)
        # Наивный (и неверный) клиент: HMAC-ключ = PEM публичного ключа.
        forged = joserfc_jwt.encode(
            {"alg": "HS256"}, _claims(), OctKey.import_key(key.as_pem().decode())
        )
        with pytest.raises(JwtVerificationError):
            await backend.decode(forged)

    @pytest.mark.asyncio
    async def test_ec_key_rejected_for_rs256_algorithm(self) -> None:
        backend = JwtBackend(algorithms=["RS256"], public_key=_ec_key())
        token = joserfc_jwt.encode({"alg": "RS256"}, _claims(), _rsa_key())
        with pytest.raises(JwtVerificationError, match="Несоответствие"):
            await backend.decode(token)

    def test_assert_key_matches_alg_detects_family_mismatch(self) -> None:
        with pytest.raises(JwtVerificationError, match="Несоответствие"):
            _assert_key_matches_alg(_ec_key(), "RS256")
        with pytest.raises(JwtVerificationError, match="Несоответствие"):
            _assert_key_matches_alg(_rsa_key(), "ES256")
        # Совпадение — без ошибки.
        _assert_key_matches_alg(_rsa_key(), "RS256")
        _assert_key_matches_alg(_ec_key(), "ES256")


class TestConstructorContract:
    """Инварианты конструктора :class:`JwtBackend`."""

    def test_mixed_symmetric_and_asymmetric_rejected(self) -> None:
        class FakeJwks:
            url = ""

            async def get_key(self, kid: str) -> dict[str, Any] | None:
                return None

        with pytest.raises(ValueError, match="смешивать"):
            JwtBackend(
                algorithms=["HS256", "RS256"],
                secret="supersecretkeywithatleast32characters!!",
                jwks=FakeJwks(),  # type: ignore[arg-type]
            )

    def test_asymmetric_requires_jwks_or_public_key(self) -> None:
        with pytest.raises(ValueError, match="jwks"):
            JwtBackend(algorithms=["RS256"])

    def test_symmetric_requires_secret(self) -> None:
        with pytest.raises(ValueError, match="secret"):
            JwtBackend(algorithms=["HS256"], secret=None)


class TestLowLevelDecode:
    """Low-level :func:`jwt_backend.decode` — явный отказ по алгоритму."""

    def test_decode_rejects_algorithm_outside_allowlist(self) -> None:
        token = _hs256_token("supersecretkeywithatleast32characters!!")
        with pytest.raises(JwtVerificationError, match="не разрешён"):
            low_level_decode(
                token,
                algorithms=["RS256"],
                secret="supersecretkeywithatleast32characters!!",
            )

    def test_decode_rejects_hs_token_in_asymmetric_mode(self) -> None:
        token = _hs256_token("supersecretkeywithatleast32characters!!")
        with pytest.raises(JwtVerificationError):
            low_level_decode(token, algorithms=["RS256"], public_key=_rsa_key())
