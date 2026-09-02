"""JwtBackend class — high-level JWT verifier поверх ``joserfc`` (S56 M2-#4 split).

Extracted из :mod:`jwt_backend` (single-file 461 LOC → sub-package split)
для single-responsibility:
- ``jwt_backend.py`` — низкоуровневые: errors, encode, decode, helpers
- ``jwt_backend_class.py`` — высокоуровневый: :class:`JwtClaims`,
  :class:`JwtBackend` (class with verify() адаптер)

Re-exported из :mod:`jwt_backend` для backward-compat public API.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from joserfc import jwt as joserfc_jwt
from joserfc.errors import BadSignatureError, DecodeError, ExpiredTokenError
from joserfc.jwk import ECKey, OctKey, RSAKey

from src.backend.core.auth import AuthContext, AuthMethod
from src.backend.core.auth.jwks_cache import JwksCache
from src.backend.core.auth.jwt_backend_helpers import (
    JwtVerificationError,
    _SYMMETRIC_ALGS,
    _ASYMMETRIC_ALGS,
    _audience_list,
    _parse_header_unsafe,
    _validate_jwt_secret_strength,
)
from src.backend.core.logging import get_logger

__all__ = ("JwtBackend", "JwtClaims")

_logger = get_logger(__name__)


@dataclass
class JwtClaims:
    """Распакованные verified-claims JWT."""

    sub: str
    iss: str | None
    aud: str | list[str] | None
    exp: int | None
    jti: str | None
    raw: dict[str, Any] = field(default_factory=dict)


@dataclass
class JwtBackend:
    """JWT-верификатор поверх ``joserfc``.

    Args:
        algorithms: Список допустимых алгоритмов (whitelist).
        secret: HS-секрет (для симметричных алгоритмов).
        jwks: JWKS-кеш (для асимметричных алгоритмов).
        audience: Ожидаемый ``aud`` (str / list / None для отключения).
        issuer: Ожидаемый ``iss`` (str / None).
        leeway: Допустимое отклонение времени в секундах для exp/nbf.
        blacklist: Опциональный blacklist (jti revocation).

    """

    method: AuthMethod = AuthMethod.JWT
    algorithms: list[str] = field(default_factory=lambda: ["RS256"])
    secret: str | None = None
    jwks: JwksCache | None = None
    audience: str | list[str] | None = None
    issuer: str | None = None
    leeway: int = 60
    blacklist: Any | None = None

    def __post_init__(self) -> None:
        if not self.algorithms:
            raise ValueError("JwtBackend: algorithms не может быть пустым")
        for alg in self.algorithms:
            if alg not in _SYMMETRIC_ALGS and alg not in _ASYMMETRIC_ALGS:
                raise ValueError(f"JwtBackend: неподдерживаемый алгоритм {alg}")
        if any(a in _ASYMMETRIC_ALGS for a in self.algorithms) and self.jwks is None:
            raise ValueError(
                "JwtBackend: для асимметричных алгоритмов требуется jwks-кеш"
            )
        if any(a in _SYMMETRIC_ALGS for a in self.algorithms) and not self.secret:
            raise ValueError("JwtBackend: для симметричных алгоритмов требуется secret")
        # S174 M9.3: weak-secret gate для HS256/384/512 (per S172 M8.3
        # pattern extension). 256-bit secret (32 bytes / 256-bit) минимум
        # для HS256 — RFC 7518. 32+ chars обеспечивают ≥ 256 бит entropy
        # при random-bytes secret. Reject trivially weak secrets.
        if any(a in _SYMMETRIC_ALGS for a in self.algorithms) and self.secret:
            strength = _validate_jwt_secret_strength(self.secret)
            if not strength.is_acceptable:
                raise ValueError(
                    f"JwtBackend: weak HS-secret rejected ({len(strength.issues)} "
                    f"issue(s)): {', '.join(strength.issues)}. "
                    f"Use random-bytes secret of ≥ 32 chars (RFC 7518 256-bit)."
                )

    async def _resolve_key(self, header: dict[str, Any]) -> Any:
        alg = header.get("alg")
        if alg in _SYMMETRIC_ALGS:
            assert self.secret is not None  # nosec
            return OctKey.import_key(self.secret)
        if alg in _ASYMMETRIC_ALGS:
            assert self.jwks is not None  # nosec
            kid = header.get("kid")
            if not kid:
                raise JwtVerificationError("Отсутствует kid в заголовке JWT")
            jwk = await self.jwks.get_key(kid)
            if not jwk:
                raise JwtVerificationError(f"Ключ {kid} не найден в JWKS")
            kty = jwk.get("kty")
            if kty == "RSA":
                return RSAKey.import_key(jwk)
            if kty == "EC":
                return ECKey.import_key(jwk)
            raise JwtVerificationError(f"Неподдерживаемый kty в JWKS: {kty}")
        raise JwtVerificationError(f"Алгоритм {alg} не в списке разрешённых")

    async def decode(self, token: str) -> JwtClaims:
        """Верифицирует токен и возвращает извлечённые claims.

        При ``feature_flags.auth_joserfc = True`` (DEPRECATED, S67 W2)
        ранее делегировал в :mod:`jwt_backend_joserfc`. Shim удалён,
        feature flag — no-op. Используется canonical реализация.
        S68 W1: feature flag полностью удалён.

        Raises:
            JwtVerificationError: При любой ошибке валидации.

        """
        header = _parse_header_unsafe(token)
        alg = header.get("alg")
        if alg not in self.algorithms:
            raise JwtVerificationError(
                f"Алгоритм {alg} не разрешён (allow={self.algorithms})"
            )

        try:
            key = await self._resolve_key(header)
        except JwtVerificationError:
            raise

        try:
            decoded = joserfc_jwt.decode(token, key=key, algorithms=self.algorithms)
        except BadSignatureError as exc:
            raise JwtVerificationError("Неверная подпись JWT") from exc
        except DecodeError as exc:
            raise JwtVerificationError(f"Ошибка декодирования JWT: {exc}") from exc

        claims = decoded.claims
        # Валидация expiry / nbf / iss / aud.
        try:
            options: dict[str, Any] = {}
            if self.issuer:
                options["iss"] = {"essential": True, "value": self.issuer}
            if self.audience:
                options["aud"] = {
                    "essential": True,
                    "values": _audience_list(self.audience),
                }
            claims_request = joserfc_jwt.JWTClaimsRegistry(
                leeway=self.leeway, **options
            )
            claims_request.validate(claims)
        except ExpiredTokenError as exc:
            raise JwtVerificationError("JWT истёк") from exc
        except Exception as exc:
            raise JwtVerificationError(f"Неверные claims JWT: {exc}") from exc

        jti = claims.get("jti")
        if jti and self.blacklist is not None:
            try:
                if await self.blacklist.is_revoked(jti):
                    raise JwtVerificationError("JWT отозван (blacklist)")
            except JwtVerificationError:
                raise
            except Exception as exc:
                # Fail-closed: если blacklist недоступен, лучше отказать в
                # валидации, чем принять потенциально revoked токен.
                _logger.error("JWT blacklist check failed (fail-closed): %s", exc)
                raise JwtVerificationError("JWT blacklist недоступен") from exc

        # S18 W4 (S-L8-5): batch-revoke barrier по iat. Проверяется
        # независимо от jti — токен может иметь iat без jti. hasattr-guard
        # для backward-compat с blacklist-mock'ами без is_iat_revoked.
        if self.blacklist is not None and hasattr(self.blacklist, "is_iat_revoked"):
            iat = claims.get("iat")
            try:
                if await self.blacklist.is_iat_revoked(iat):
                    raise JwtVerificationError(
                        "JWT отозван (rotation: iat < revoke_before)"
                    )
            except JwtVerificationError:
                raise
            except Exception as exc:
                # Fail-closed: см. is_revoked.
                _logger.error("JWT iat-revoke check failed (fail-closed): %s", exc)
                raise JwtVerificationError("JWT blacklist недоступен") from exc

        return JwtClaims(
            sub=str(claims.get("sub") or ""),
            iss=claims.get("iss"),
            aud=claims.get("aud"),
            exp=claims.get("exp"),
            jti=jti,
            raw=dict(claims),
        )

    async def verify(self, request: Any) -> AuthContext | None:
        """Адаптер для FastAPI: извлекает ``Authorization: Bearer *** и верифицирует.

        S68 W1: dead branch (``auth_joserfc`` delegation в удалённый
        ``jwt_backend_joserfc`` shim) убран. Используется canonical
        реализация всегда.

        Returns:
            ``AuthContext`` при успехе; ``None`` если header отсутствует или
            токен невалиден (детали в логе).

        """
        auth = request.headers.get("Authorization", "")
        if not auth.startswith("Bearer "):
            return None
        token = auth[7:]
        try:
            claims = await self.decode(token)
        except JwtVerificationError as exc:
            _logger.info("JWT verify failed: %s", exc)
            return None
        return AuthContext(self.method, claims.sub, claims.raw)