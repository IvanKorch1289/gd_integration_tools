"""JWT backend — canonical implementation поверх ``joserfc`` (low-level).

Wave [s2/k1-2-jwt-jwks] — V7 Auth-стек R1. Поддержка алгоритмов:
* HS256 / HS384 / HS512 — симметричная подпись (shared secret);
* RS256 / RS384 / RS512 — асимметричная (RSA + JWKS lookup);
* ES256 / ES384 — асимметричная (ECDSA + JWKS lookup).

S56 M2-#4 split: класс :class:`JwtBackend` + :class:`JwtClaims` extracted
в :mod:`jwt_backend_class` (high-level). Этот модуль хранит только
низкоуровневые helpers: errors, encode, decode, _audience_list,
_parse_header_unsafe, _validate_jwt_secret_strength.

Backward-compat: ``JwtBackend``/``JwtClaims`` re-exported из
``jwt_backend_class`` для external callers (auth_selector, mobile_jwt,
auth/facade, mobile_jwt_revocation, mobile_jwt_redis, di/providers/auth).

S67 W2: удалён parallel shim ``jwt_backend_joserfc.py``. Текущая
реализация — единственная. ``feature_flags.auth_joserfc`` flag
deprecated (no-op).
S68 W1: ``feature_flags.auth_joserfc`` field удалён (no-op cleanup,
TD-S67-feature-flag-deprecation).
"""

from __future__ import annotations

from typing import Any

from joserfc import jwt as joserfc_jwt
from joserfc.errors import BadSignatureError, DecodeError
from joserfc.jwk import OctKey  # S56 M2-#4: re-added (используется в encode/decode)

# S56 M2-#4: re-export JwtBackend + JwtClaims для backward-compat public API.
# External callers (auth_selector.py, mobile_jwt.py, mobile_jwt_revocation.py,
# auth/facade.py, di/providers/auth.py) импортируют из jwt_backend напрямую.
from src.backend.core.auth.jwt_backend_class import (  # noqa: E402,F401
    JwtBackend,
    JwtClaims,
)
from src.backend.core.auth.jwt_backend_helpers import (
    _ASYMMETRIC_ALGS,
    _SYMMETRIC_ALGS,
    JwtSecretStrengthReport,  # re-exported (S56 M2-#4: moved из jwt_backend)
    JwtVerificationError,  # re-exported (S56 M2-#4: moved из jwt_backend)
    _parse_header_unsafe,
)
from src.backend.core.logging import get_logger

__all__ = (
    "JwtBackend",
    "JwtClaims",
    "JwtSecretStrengthReport",
    "JwtVerificationError",
    "decode",
    "encode",
)

_logger = get_logger(__name__)


def encode(
    subject: str,
    claims: dict[str, Any] | None = None,
    *,
    alg: str = "HS256",
    secret: str | None = None,
    private_key: Any = None,
    kid: str | None = None,
    expires_in: int = 3600,
    issuer: str | None = None,
) -> tuple[str, int]:
    """S67 W2: top-level encode (canonical, replaces shim's encode).

    Создаёт подписанный JWT через ``joserfc``.

    Args:
        subject: ``sub`` claim (user identity).
        claims: Дополнительные claims (auth_method, is_superuser, …).
        alg: Алгоритм подписи (HS256, RS256, …).
        secret: Shared secret для HS-алгоритмов.
        private_key: Приватный ключ для RS/EC-алгоритмов (joserfc RSAKey / ECKey).
        kid: Идентификатор ключа (``kid`` в header).
        expires_in: TTL в секундах (default 3600 = 1h).
        issuer: ``iss`` claim (optional).

    Returns:
        Кортеж ``(token_str, expires_in)``.

    Raises:
        ValueError: Если ни ``secret``, ни ``private_key`` не переданы.

    """
    import time as _time

    now = int(_time.time())
    full_claims: dict[str, Any] = {"sub": subject, "iat": now, "exp": now + expires_in}
    if issuer:
        full_claims["iss"] = issuer
    if claims:
        full_claims.update(claims)

    header: dict[str, Any] = {"alg": alg}
    if kid is not None:
        header["kid"] = kid

    if alg in _SYMMETRIC_ALGS:
        if not secret:
            raise ValueError("encode: secret обязателен для симметричных алгоритмов")
        key = OctKey.import_key(secret)
    elif alg in _ASYMMETRIC_ALGS:
        if private_key is None:
            raise ValueError(
                "encode: private_key обязателен для асимметричных алгоритмов"
            )
        key = private_key
    else:
        raise ValueError(f"encode: неподдерживаемый алгоритм {alg}")

    token = joserfc_jwt.encode(header, full_claims, key)
    return token, expires_in


def decode(
    token: str,
    *,
    algorithms: list[str],
    secret: str | None = None,
    public_key: Any = None,
) -> dict[str, Any]:
    """Декодирует и верифицирует JWT через joserfc (без валидации claims).

    Низкоуровневая функция — валидацию iss/aud/exp производить поверх
    (через :meth:`JwtBackend.decode`).

    Args:
        token: Компактный JWT-строка.
        algorithms: Разрешённые алгоритмы.
        secret: Shared secret для HS-алгоритмов.
        public_key: Публичный ключ для RS/EC-алгоритмов.

    Returns:
        Словарь claims из payload.

    Raises:
        JwtVerificationError: При ошибке подписи или декодирования.

    """
    try:
        header_raw = _parse_header_unsafe(token)
        alg = header_raw.get("alg")

        if alg in _SYMMETRIC_ALGS:
            if not secret:
                raise JwtVerificationError(
                    "decode: secret обязателен для симметричных алгоритмов"
                )
            key = OctKey.import_key(secret)
        elif alg in _ASYMMETRIC_ALGS:
            if public_key is None:
                raise JwtVerificationError(
                    "decode: public_key обязателен для асимметричных алгоритмов"
                )
            key = public_key
        else:
            raise JwtVerificationError(f"decode: неподдерживаемый алгоритм {alg}")

        decoded = joserfc_jwt.decode(token, key=key, algorithms=algorithms)
        return dict(decoded.claims)
    except JwtVerificationError:
        raise
    except (BadSignatureError, DecodeError) as exc:
        raise JwtVerificationError(f"Ошибка верификации JWT: {exc}") from exc
    except Exception as exc:
        raise JwtVerificationError(f"Ошибка декодирования JWT: {exc}") from exc


# S56 M2-#4: JwtClaims + JwtBackend extracted в :mod:`jwt_backend_class`
# (re-exported в начале этого модуля для backward-compat public API).
# Этот файл хранит только low-level: errors, encode, decode.
# Helpers (_audience_list, _parse_header_unsafe, _validate_jwt_secret_strength,
# JwtSecretStrengthReport, _ASYMMETRIC_ALGS, _SYMMETRIC_ALGS) extracted
# в :mod:`jwt_backend_helpers` для устранения circular import.
