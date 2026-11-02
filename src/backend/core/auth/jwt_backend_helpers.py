"""JWT backend helpers — shared low-level utilities (S56 M2-#4 split).

Извлечено из :mod:`jwt_backend` для устранения circular import после
split (jwt_backend_class не может import from jwt_backend, который
re-export от jwt_backend_class). Helpers — third-party: оба модуля
(jwt_backend + jwt_backend_class) импортируют отсюда.

Содержимое:
- :class:`JwtVerificationError` — exception (moved here для устранения circular)
- :data:`_ASYMMETRIC_ALGS` / :data:`_SYMMETRIC_ALGS` — algorithm allowlist
- :func:`_audience_list` — aud parameter normalization
- :func:`_parse_header_unsafe` — JWT header extraction без verify
- :class:`JwtSecretStrengthReport` + :func:`_validate_jwt_secret_strength`
  — S174 M9.3 weak-HS-secret detector
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any


class JwtVerificationError(Exception):
    """Ошибка верификации JWT (expired/bad-sig/wrong-claims/revoked).

    S56 M2-#4: moved из :mod:`jwt_backend` сюда для устранения circular
    import chain. Определена как standalone exception без зависимостей
    от JwtBackend / JwtClaims.
    """


# ── Algorithm allowlist (S56 M2-#4 extracted) ─────────────────────────────


_ASYMMETRIC_ALGS = frozenset(
    {"RS256", "RS384", "RS512", "ES256", "ES384", "ES512", "PS256", "PS384", "PS512"}
)
_SYMMETRIC_ALGS = frozenset({"HS256", "HS384", "HS512"})

# ADR-0411: соответствие «семейство алгоритма → тип ключа».
# Используется для явного отказа при несоответствии алгоритма и ключа
# (algorithm confusion): HMAC-подпись публичным ключом и наоборот.
_ALG_KEY_FAMILY: dict[str, str] = {
    "RS256": "RSA",
    "RS384": "RSA",
    "RS512": "RSA",
    "PS256": "RSA",
    "PS384": "RSA",
    "PS512": "RSA",
    "ES256": "EC",
    "ES384": "EC",
    "ES512": "EC",
    "HS256": "oct",
    "HS384": "oct",
    "HS512": "oct",
}


def _key_family(key: Any) -> str | None:
    """Возвращает семейство ключа (``RSA`` / ``EC`` / ``oct``) или ``None``.

    Args:
        key: JWK-объект joserfc (``RSAKey`` / ``ECKey`` / ``OctKey``).

    Returns:
        Строка семейства или ``None``, если тип ключа не распознан.

    """
    from joserfc.jwk import ECKey, OctKey, RSAKey

    if isinstance(key, OctKey):
        return "oct"
    if isinstance(key, RSAKey):
        return "RSA"
    if isinstance(key, ECKey):
        return "EC"
    return None


def _assert_key_matches_alg(key: Any, alg: str) -> None:
    """Проверяет, что тип ключа соответствует алгоритму подписи (ADR-0411).

    Запрещает algorithm confusion: RSA/EC-ключ не принимается как HMAC-секрет
    и наоборот. Для нераспознанного типа ключа проверка пропускается —
    подпись всё равно проверяет joserfc.

    Args:
        key: JWK-объект joserfc.
        alg: Алгоритм из JWT-заголовка.

    Raises:
        JwtVerificationError: Если тип ключа не соответствует алгоритму.

    """
    expected = _ALG_KEY_FAMILY.get(alg)
    actual = _key_family(key)
    if expected is None or actual is None:
        return
    if actual != expected:
        raise JwtVerificationError(
            f"Несоответствие алгоритма и ключа: {alg} требует ключ типа "
            f"{expected}, получен {actual}"
        )


# ── Audience parameter normalization ───────────────────────────────────────


def _audience_list(audience: str | list[str] | None) -> list[str]:
    if audience is None:
        return []
    if isinstance(audience, str):
        return [audience]
    return list(audience)


# ── JWT header extraction без verify ─────────────────────────────────────


def _parse_header_unsafe(token: str) -> dict[str, Any]:
    """Извлекает JWT header без проверки подписи (для определения alg/kid).

    Используется чтобы выбрать корректный ключ из JWKS до signature-verify.
    Сам по себе **не валидирует** токен — это делается ниже через
    ``joserfc.jwt.decode`` с резолвленным ключом.
    """
    import base64
    import json

    try:
        header_b64 = token.split(".")[0]
        header_b64 += "=" * (-len(header_b64) % 4)
        header_bytes = base64.urlsafe_b64decode(header_b64.encode())
        header = json.loads(header_bytes)
    except Exception as exc:
        raise JwtVerificationError(f"Некорректный JWT header: {exc}") from exc
    if not isinstance(header, dict):
        raise JwtVerificationError("JWT header не является объектом")
    return header


# ── S174 M9.3: weak-HS-secret detector (lightweight) ──────────────────────


# S174 M9.3: minimum acceptable length для HS256/384/512 secret.
# Per RFC 7518: 256-bit secret (32 bytes / 256-bit) минимум для HS256.
# Reject < 32 chars per production hardening convention.
_MIN_JWT_SECRET_LENGTH: int = 32

# S174 M9.3: blacklist trivially-weak HS secrets.
_WEAK_JWT_SECRETS: frozenset[str] = frozenset(
    {
        "",
        "secret",
        "changeme",
        "default",
        "test",
        "admin",
        "password",
        "jwt-secret",
        "my-secret",
        "supersecret",
    }
)


@dataclass(frozen=True, slots=True)
class JwtSecretStrengthReport:
    """S174 M9.3: result of :func:`_validate_jwt_secret_strength`."""

    is_acceptable: bool
    issues: tuple[str, ...]
    length: int
    entropy_bits: float


def _validate_jwt_secret_strength(secret: str) -> JwtSecretStrengthReport:
    """Heuristic: length + blacklist + entropy.

    Per S174 M9.3 lightweight scope: NOT zxcvbn-level analysis.
    Production-grade HS256 secret: 32+ chars random bytes
    (``secrets.token_urlsafe(32)``).
    """
    issues: list[str] = []
    if not secret:
        issues.append("empty")
    if len(secret) < _MIN_JWT_SECRET_LENGTH:
        issues.append(f"too_short (length={len(secret)} < {_MIN_JWT_SECRET_LENGTH})")
    if secret in _WEAK_JWT_SECRETS:
        issues.append("blacklisted_common_secret")
    if secret and len(set(secret)) == 1:
        issues.append("all_same_character")
    unique = len(set(secret)) if secret else 0
    entropy_bits = (
        (unique.bit_length() if unique else 0) * len(secret) if secret else 0.0
    )
    # S174 M9.3: heuristic — не strict RFC 7518 enforcement.
    # Length ≥ 32 chars — primary gate (RFC 7518). Entropy check —
    # только warning-level (если unique chars < 8, flag для явных
    # patterns). RFC 7518 min entropy 256 — теоретически max bound
    # для brute-force-resistance.
    if entropy_bits < 128.0 and len(secret) >= 32:
        issues.append(
            f"low_entropy (estimate={entropy_bits:.1f} bits; "
            f"RFC 7518 recommends 256+ for HS256)"
        )

    is_acceptable = not issues
    return JwtSecretStrengthReport(
        is_acceptable=is_acceptable,
        issues=tuple(issues),
        length=len(secret),
        entropy_bits=entropy_bits,
    )


__all__ = (
    "JwtVerificationError",
    "_ASYMMETRIC_ALGS",
    "_SYMMETRIC_ALGS",
    "_assert_key_matches_alg",
    "_audience_list",
    "_key_family",
    "_parse_header_unsafe",
    "_validate_jwt_secret_strength",
    "JwtSecretStrengthReport",
)
