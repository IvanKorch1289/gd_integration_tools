"""S67 W4: regression tests для ``jwt_backend.encode()`` (canonical).

S67 W2: ``encode()`` переехал из shim в ``jwt_backend.py`` (canonical).
Раньше ``auth_login.py:173`` использовал shim's ``encode(claims, ...)``
НЕ совместимую с call signature ``encode(subject=..., claims=...)``
→ TypeError маскировался ``try/except``, mock token fallback.

Canonical ``encode()``:
1. Принимает ``(subject, claims, *, alg, secret, expires_in, ...)``;
2. Возвращает ``(token_str, expires_in)`` tuple;
3. Auto-добавляет ``iat``, ``exp`` claims (TTL = expires_in);
4. Поддерживает HS* и RS*/ES* алгоритмы через joserfc.

Эти тесты ЗАКРЕПЛЯЮТ правильное поведение, чтобы кто-то
"упростил" encode обратно до shim's broken signature.
"""

from __future__ import annotations

import time

import pytest
from joserfc import jwt as joserfc_jwt
from joserfc.jwk import OctKey

from src.backend.core.auth.jwt_backend import (
    encode,
    decode,
    JwtVerificationError,
)


SECRET = "test-secret-very-long-32-bytes!"


def test_encode_returns_token_and_ttl_tuple() -> None:
    """``encode()`` возвращает ``(token_str, expires_in)`` кортеж."""
    token, ttl = encode(subject="alice", claims={"role": "admin"}, secret=SECRET)

    assert isinstance(token, str)
    assert isinstance(ttl, int)
    assert ttl == 3600  # default
    assert len(token.split(".")) == 3  # JWT compact serialization


def test_encode_includes_iat_and_exp_claims() -> None:
    """``encode()`` auto-добавляет ``iat`` и ``exp`` (TTL=expires_in)."""
    before = int(time.time())
    token, ttl = encode(subject="alice", claims={"role": "user"}, secret=SECRET)
    after = int(time.time())

    # Decode без проверки подписи (мы только в payload).
    claims = joserfc_jwt.decode(token, key=OctKey.import_key(SECRET), algorithms=["HS256"]).claims

    assert claims["sub"] == "alice"
    assert claims["role"] == "user"
    assert "iat" in claims
    assert "exp" in claims
    # iat в диапазоне [before, after]
    assert before <= claims["iat"] <= after
    # exp = iat + expires_in
    assert claims["exp"] == claims["iat"] + ttl
    assert claims["exp"] - claims["iat"] == 3600


def test_encode_with_custom_expires_in() -> None:
    """``encode()`` уважает ``expires_in`` параметр (default 3600, можно 60)."""
    _, ttl_60 = encode(subject="bob", claims=None, secret=SECRET, expires_in=60)
    assert ttl_60 == 60

    _, ttl_7200 = encode(subject="carol", claims=None, secret=SECRET, expires_in=7200)
    assert ttl_7200 == 7200


def test_encode_with_issuer() -> None:
    """``encode(issuer=...)`` добавляет ``iss`` claim."""
    token, _ = encode(
        subject="alice", claims=None, secret=SECRET, issuer="https://example.com"
    )
    claims = joserfc_jwt.decode(token, key=OctKey.import_key(SECRET), algorithms=["HS256"]).claims
    assert claims["iss"] == "https://example.com"


def test_encode_without_secret_raises_value_error() -> None:
    """HS-алгоритм без ``secret`` поднимает ``ValueError``."""
    with pytest.raises(ValueError, match="secret обязателен"):
        encode(subject="alice", claims=None, secret=None)


def test_encode_with_unsupported_alg_raises_value_error() -> None:
    """Неизвестный алгоритм поднимает ``ValueError``."""
    with pytest.raises(ValueError, match="неподдерживаемый алгоритм"):
        encode(subject="alice", claims=None, secret=SECRET, alg="MD5")  # type: ignore[arg-type]


def test_decode_low_level_uses_same_joserfc() -> None:
    """Round-trip: ``encode()`` → ``decode()`` (low-level) возвращает claims."""
    token, _ = encode(subject="alice", claims={"role": "admin"}, secret=SECRET)
    decoded = decode(token, algorithms=["HS256"], secret=SECRET)

    assert decoded["sub"] == "alice"
    assert decoded["role"] == "admin"
    assert "iat" in decoded
    assert "exp" in decoded


def test_decode_raises_on_bad_signature() -> None:
    """``decode()`` с неверным secret поднимает ``JwtVerificationError``."""
    token, _ = encode(subject="alice", claims=None, secret=SECRET)
    with pytest.raises(JwtVerificationError, match="Ошибка верификации JWT"):
        decode(token, algorithms=["HS256"], secret="WRONG-SECRET")


def test_auth_login_call_signature_works() -> None:
    """Regression: auth_login.py:173 использует ``encode(subject=, claims=)``.

    Canonical encode() поддерживает эту сигнатуру. До S67 W2 — shim's
    encode(claims, ...) падал с TypeError → try/except fallback на
    mock token.
    """
    # Воспроизводим ровно call pattern из auth_login.py:173
    token, expires_in = encode(
        subject="testuser",
        claims={"auth_method": "password", "is_superuser": False},
        secret=SECRET,
    )

    assert isinstance(token, str)
    assert expires_in == 3600  # default
    # Token должен декодироваться с теми же claims
    decoded = decode(token, algorithms=["HS256"], secret=SECRET)
    assert decoded["sub"] == "testuser"
    assert decoded["auth_method"] == "password"
    assert decoded["is_superuser"] is False
