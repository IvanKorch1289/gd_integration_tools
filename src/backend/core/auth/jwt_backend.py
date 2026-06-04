"""JWT backend — dispatcher с feature-flag ``auth_joserfc``.

Wave [s2/k1-2-jwt-jwks] — V7 Auth-стек R1. Поддержка алгоритмов:
* HS256 / HS384 / HS512 — симметричная подпись (shared secret);
* RS256 / RS384 / RS512 — асимметричная (RSA + JWKS lookup);
* ES256 / ES384 — асимметричная (ECDSA + JWKS lookup).

Критический prod-bug: ранее ``auth_selector.py`` импортировал
``python-jose``, который отсутствует в pyproject.toml → ``ImportError``
при первом Bearer-token-запросе на проде. Этот backend заменяет
данную секцию верификации и поднимается через DI.

Feature-flag [s2/k1-w1-joserfc]:
    * ``feature_flags.auth_joserfc = False`` (default-OFF) — текущая
      joserfc-реализация непосредственно в этом модуле.
    * ``feature_flags.auth_joserfc = True`` — делегирование в
      :mod:`jwt_backend_joserfc` (параллельный shim), что позволяет
      переключить бэкенд без удаления python-jose кода из основного пути.

    Импорт feature_flags и проверка выполняются внутри методов (lazy),
    чтобы не сломать startup при ещё не инициализированном Settings.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from joserfc import jwt as joserfc_jwt
from joserfc.errors import BadSignatureError, DecodeError, ExpiredTokenError
from joserfc.jwk import ECKey, OctKey, RSAKey

from src.backend.core.auth import AuthContext, AuthMethod
from src.backend.core.auth.jwks_cache import JwksCache

__all__ = ("JwtBackend", "JwtClaims", "JwtVerificationError")

_logger = logging.getLogger(__name__)

_ASYMMETRIC_ALGS = frozenset(
    {"RS256", "RS384", "RS512", "ES256", "ES384", "ES512", "PS256", "PS384", "PS512"}
)
_SYMMETRIC_ALGS = frozenset({"HS256", "HS384", "HS512"})


class JwtVerificationError(Exception):
    """Ошибка верификации JWT (expired/bad-sig/wrong-claims/revoked)."""


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

    async def _resolve_key(self, header: dict[str, Any]) -> Any:
        alg = header.get("alg")
        if alg in _SYMMETRIC_ALGS:
            assert self.secret is not None
            return OctKey.import_key(self.secret)
        if alg in _ASYMMETRIC_ALGS:
            assert self.jwks is not None
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

        При ``feature_flags.auth_joserfc = True`` делегирует в
        :mod:`jwt_backend_joserfc`. Импорт выполняется lazy (внутри метода)
        чтобы не нарушить startup при ещё не инициализированном Settings.

        Raises:
            JwtVerificationError: При любой ошибке валидации.
        """
        # Lazy feature-flag check — импорт внутри метода для избежания
        # circular imports и корректного lazy-loading Settings на старте.
        from src.backend.core.config.features import feature_flags

        if feature_flags.auth_joserfc:
            import src.backend.core.auth.jwt_backend_joserfc as _joserfc_shim

            shim = _joserfc_shim.JwtBackend(
                method=self.method,
                algorithms=self.algorithms,
                secret=self.secret,
                jwks=self.jwks,
                audience=self.audience,
                issuer=self.issuer,
                leeway=self.leeway,
                blacklist=self.blacklist,
            )
            shim_claims = await shim.decode(token)
            # Конвертируем shim-тип JwtClaims → локальный JwtClaims
            return JwtClaims(
                sub=shim_claims.sub,
                iss=shim_claims.iss,
                aud=shim_claims.aud,
                exp=shim_claims.exp,
                jti=shim_claims.jti,
                raw=shim_claims.raw,
            )

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
                _logger.warning("JWT blacklist check failed: %s", exc)

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
                _logger.warning("JWT iat-revoke check failed: %s", exc)

        return JwtClaims(
            sub=str(claims.get("sub") or ""),
            iss=claims.get("iss"),
            aud=claims.get("aud"),
            exp=claims.get("exp"),
            jti=jti,
            raw=dict(claims),
        )

    async def verify(self, request: Any) -> AuthContext | None:
        """Адаптер для FastAPI: извлекает ``Authorization: Bearer ...`` и верифицирует.

        При ``feature_flags.auth_joserfc = True`` делегирует в
        :mod:`jwt_backend_joserfc`. Импорт выполняется lazy (внутри метода).

        Returns:
            ``AuthContext`` при успехе; ``None`` если header отсутствует или
            токен невалиден (детали в логе).
        """
        from src.backend.core.config.features import feature_flags

        if feature_flags.auth_joserfc:
            import src.backend.core.auth.jwt_backend_joserfc as _joserfc_shim

            shim = _joserfc_shim.JwtBackend(
                method=self.method,
                algorithms=self.algorithms,
                secret=self.secret,
                jwks=self.jwks,
                audience=self.audience,
                issuer=self.issuer,
                leeway=self.leeway,
                blacklist=self.blacklist,
            )
            return await shim.verify(request)

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


def _audience_list(audience: str | list[str] | None) -> list[str]:
    if audience is None:
        return []
    if isinstance(audience, str):
        return [audience]
    return list(audience)


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
