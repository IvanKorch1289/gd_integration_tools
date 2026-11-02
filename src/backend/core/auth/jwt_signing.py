"""Выпуск JWT по конфигурации ``security`` (ADR-0411).

Единая точка подписи: алгоритм, ключ и ``kid`` разрешаются из
:class:`SecureSettings` — симметричный режим (``HS*``) использует
``security.secret_key``, асимметричный (``RS*``/``ES*``) — приватный
ключ из ``security.jwt_private_key_path`` (PKCS#8 PEM).

Правила (fail-closed):

* «тихой» downgrade запрещён — явный ``alg``, несовместимый по семейству
  с настроенным алгоритмом, приводит к ошибке, а не к подписи HS-токена
  в RS-режиме;
* в асимметричном режиме shared secret не используется вообще;
* отсутствие приватного ключа — ошибка конфигурации, а не подпись
  «как получится».
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any

from src.backend.core.auth.jwt_backend import encode as _encode
from src.backend.core.logging import get_logger

__all__ = ("SigningParams", "encode_token", "resolve_signing_params")

_logger = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class SigningParams:
    """Параметры подписи JWT, разрешённые из конфигурации.

    Attrs:
        alg: Алгоритм подписи (``HS256`` / ``RS256`` / ``ES256``).
        secret: Shared secret (только для симметричных алгоритмов).
        private_key: JWK-объект приватного ключа (только для асимметричных).
        kid: Идентификатор ключа в заголовке JWT (``None`` — не проставлять).

    """

    alg: str
    secret: str | None
    private_key: Any | None
    kid: str | None


def _secret_value(raw: Any) -> str:
    """Достаёт значение ``SecretStr`` (или строки) без маскирования."""
    return raw.get_secret_value() if hasattr(raw, "get_secret_value") else str(raw)


def resolve_signing_params(settings: Any | None = None) -> SigningParams:
    """Разрешает параметры подписи из настроек безопасности.

    Args:
        settings: Источник настроек (по умолчанию — глобальный
            ``secure_settings``).

    Returns:
        :class:`SigningParams` — алгоритм, ключ и ``kid``.

    Raises:
        ValueError: Если в асимметричном режиме не задан приватный ключ
            (``security.jwt_private_key_path``) или он недоступен.

    """
    if settings is None:
        from src.backend.core.config.security import secure_settings

        settings = secure_settings

    alg = str(getattr(settings, "algorithm", "HS256"))
    kid = str(getattr(settings, "jwt_kid", "") or "") or None

    if alg.startswith("HS"):
        return SigningParams(
            alg=alg,
            secret=_secret_value(settings.secret_key),
            private_key=None,
            kid=kid,
        )

    private_path = str(getattr(settings, "jwt_private_key_path", "") or "")
    if not private_path:
        raise ValueError(
            f"Асимметричный алгоритм {alg} требует security.jwt_private_key_path "
            "(PKCS#8 PEM): без приватного ключа выпуск токенов невозможен."
        )
    from src.backend.core.security.jwt_keys import (
        derive_kid,
        load_private_key_pem,
        public_pem_from_private,
    )

    private_key = load_private_key_pem(private_path)
    if kid is None:
        private_pem = Path(private_path).read_text(encoding="utf-8")
        kid = derive_kid(public_pem_from_private(private_pem))
    return SigningParams(alg=alg, secret=None, private_key=private_key, kid=kid)


def encode_token(
    subject: str,
    claims: dict[str, Any] | None = None,
    *,
    alg: str | None = None,
    secret: str | None = None,
    private_key: Any | None = None,
    kid: str | None = None,
    expires_in: int = 3600,
    issuer: str | None = None,
    settings: Any | None = None,
) -> tuple[str, int]:
    """Выпускает подписанный JWT по настройкам ``security``.

    Args:
        subject: ``sub`` claim (идентификатор пользователя).
        claims: Дополнительные claims.
        alg: Явный алгоритм; ``None`` — алгоритм из настроек.
        secret: Явный shared secret (только для симметричного режима).
        private_key: Явный приватный ключ (только для асимметричного режима).
        kid: Явный ``kid``; ``None`` — ``kid`` из настроек.
        expires_in: TTL токена в секундах.
        issuer: Значение claim ``iss``.
        settings: Источник настроек (по умолчанию — ``secure_settings``).

    Returns:
        Кортеж ``(token_str, expires_in)``.

    Raises:
        ValueError: При несовместимом алгоритме (запрет «тихого» downgrade)
            либо при отсутствии нужного ключа.

    """
    params = resolve_signing_params(settings)
    target_alg = alg or params.alg

    if target_alg.startswith("HS") != params.alg.startswith("HS"):
        raise ValueError(
            f"encode_token: алгоритм {target_alg} несовместим с настроенным "
            f"{params.alg} — «тихой» downgrade запрещён (ADR-0411)."
        )

    if target_alg.startswith("HS"):
        effective_secret = secret if secret is not None else params.secret
        if not effective_secret:
            raise ValueError(
                "encode_token: secret обязателен для симметричных алгоритмов"
            )
        return _encode(
            subject,
            claims,
            alg=target_alg,
            secret=effective_secret,
            expires_in=expires_in,
            issuer=issuer,
        )

    effective_private = private_key if private_key is not None else params.private_key
    if effective_private is None:
        raise ValueError(
            "encode_token: приватный ключ обязателен для асимметричных алгоритмов"
        )
    return _encode(
        subject,
        claims,
        alg=target_alg,
        private_key=effective_private,
        kid=kid if kid is not None else params.kid,
        expires_in=expires_in,
        issuer=issuer,
    )
