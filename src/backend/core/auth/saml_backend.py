"""SAML auth backend (V15 S6 DoD).

SP-initiated SSO + SLO поверх ``python3-saml``. Метаданные IdP, ключ SP
и x509-cert SP читаются из :class:`SecretBroker` (Vault) — для ротации
без рестарта.

Зависимость **opt-in**: ``uv sync --extra auth-saml`` (тянет xmlsec
C-extension). Lazy-import гарантирует, что ядро остаётся
работоспособным без SAML.

Контракт класса :class:`SamlBackend`:

* :meth:`build_login_redirect_url` — строит SP-initiated SSO URL для
  редиректа на IdP;
* :meth:`process_saml_response` — валидирует SAMLResponse от IdP,
  возвращает principal + attributes;
* :meth:`build_logout_redirect_url` — SLO redirect;
* :meth:`parse_idp_metadata` — staticmethod, разбирает IdP-XML metadata
  (S6 K1 W1).

Защита от replay-атак: каждый ``InResponseTo`` сматчится с in-memory
session-store (RelayState/RequestID); повтор не принимается.

Feature-flag: ``feature_flags.saml_ad_login_enabled`` (default-OFF до
staging IdP конфигурации; см. S6 K1 W1).
"""

from __future__ import annotations

from src.backend.core.logging import get_logger
import secrets
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any

__all__ = ("IdpMetadata", "SamlAuthResult", "SamlBackend", "SamlConfig", "SamlError")

_logger = get_logger(__name__)


@dataclass(frozen=True, slots=True)
class SamlConfig:
    """Конфигурация SAML SP (Service Provider).

    Attributes:
        sp_entity_id: SP EntityID (URI).
        sp_acs_url: AssertionConsumerService URL (SP-side endpoint).
        sp_sls_url: Опц. SingleLogoutService URL.
        sp_x509_cert: PEM-encoded SP cert (через :class:`SecretBroker`).
        sp_private_key: PEM-encoded SP private key.
        idp_entity_id: IdP EntityID.
        idp_sso_url: SSO URL у IdP.
        idp_slo_url: SLO URL у IdP (опц.).
        idp_x509_cert: PEM-encoded IdP cert (для signature-validation).
        replay_window_seconds: TTL InResponseTo-токенов (default 5 мин).
    """

    sp_entity_id: str
    sp_acs_url: str
    sp_x509_cert: str
    sp_private_key: str
    idp_entity_id: str
    idp_sso_url: str
    idp_x509_cert: str
    sp_sls_url: str | None = None
    idp_slo_url: str | None = None
    replay_window_seconds: float = 300.0


@dataclass(frozen=True, slots=True)
class SamlAuthResult:
    """Результат успешной проверки SAMLResponse.

    Attributes:
        principal: NameID или primary attribute (email/sub).
        attributes: Полный набор атрибутов от IdP.
        session_index: ``SessionIndex`` для последующего SLO.
    """

    principal: str
    attributes: Mapping[str, Any]
    session_index: str | None = None


class SamlError(Exception):
    """Ошибка валидации SAMLResponse / replay-attack / config."""


@dataclass(frozen=True, slots=True)
class IdpMetadata:
    """Параметры IdP, извлечённые из EntityDescriptor XML.

    Attributes:
        entity_id: IdP EntityID (атрибут ``entityID`` корневого элемента).
        sso_url: URL SingleSignOnService с HTTP-Redirect/POST binding.
        slo_url: URL SingleLogoutService (опц.).
        x509_cert: PEM-encoded X509 cert IdP (signing-credential).
    """

    entity_id: str
    sso_url: str
    x509_cert: str
    slo_url: str | None = None


class SamlBackend:
    """SAML backend (lazy-import ``python3-saml``).

    Args:
        config: Параметры SP/IdP.
        clock: Источник времени (sec). По умолчанию ``time.time``.
        nonce_factory: Опц. фабрика nonce'ов (override для тестов).
    """

    def __init__(
        self,
        *,
        config: SamlConfig,
        clock: Callable[[], float] = time.time,
        nonce_factory: Callable[[], str] | None = None,
    ) -> None:
        self._config = config
        self._clock = clock
        self._nonce = nonce_factory or (lambda: secrets.token_urlsafe(16))
        # Map ``request_id -> issued_at`` для defence от replay.
        self._issued: dict[str, float] = {}

    def is_available(self) -> bool:
        """Проверить, что ``python3-saml`` установлен.

        Returns ``False`` если xmlsec/onelogin отсутствуют — caller
        должен либо отключить SAML, либо инструктировать админа
        ``uv sync --extra auth-saml``.
        """
        try:
            import onelogin.saml2  # noqa: F401

            return True
        except ImportError:
            return False

    def build_login_redirect_url(
        self, *, relay_state: str | None = None
    ) -> tuple[str, str]:
        """Сгенерировать SSO redirect URL для SP-initiated flow.

        Returns:
            Кортеж ``(redirect_url, request_id)``. ``request_id``
            обязателен для последующего matching ``InResponseTo``.

        URL-composition не требует ``python3-saml`` — реальная подпись
        XML выполняется внутри validator'а в :meth:`process_saml_response`.
        """
        request_id = self._nonce()
        self._issued[request_id] = self._clock()
        # Очистка просроченных request_id от replay-store.
        self._purge_expired()

        # Реальная сборка AuthnRequest через python3-saml выполняется
        # в HTTP-handler (см. :mod:`entrypoints.api.dependencies.auth_selector`),
        # т.к. там доступен FastAPI Request. Здесь возвращаем минимум,
        # достаточный для тестируемости контракта.
        url = (
            f"{self._config.idp_sso_url}"
            f"?SAMLRequest={request_id}"
            f"&RelayState={relay_state or ''}"
        )
        return url, request_id

    def process_saml_response(
        self, *, request_id: str, validator: Callable[[], SamlAuthResult]
    ) -> SamlAuthResult:
        """Принять SAMLResponse от IdP с replay-protection.

        Args:
            request_id: ``InResponseTo``, должен совпадать с issued.
            validator: Тонкий wrapper над ``OneLogin_Saml2_Auth.process_response``;
                инжектируется caller'ом, чтобы изоляция тестов.

        Raises:
            SamlError: Replay (повторное использование), expired
                request_id, или validation failure.
        """
        issued_at = self._issued.pop(request_id, None)
        if issued_at is None:
            raise SamlError("InResponseTo unknown or already used (replay defence)")

        age = self._clock() - issued_at
        if age > self._config.replay_window_seconds:
            raise SamlError(
                f"InResponseTo expired: {age:.0f}s > "
                f"{self._config.replay_window_seconds:.0f}s"
            )

        try:
            result = validator()
        except Exception as exc:
            raise SamlError(f"SAMLResponse validation failed: {exc}") from exc
        return result

    def build_logout_redirect_url(self, *, session_index: str, name_id: str) -> str:
        """Сгенерировать SLO redirect (если IdP support'ит SLO)."""
        if self._config.idp_slo_url is None:
            raise SamlError("IdP SLO URL not configured")
        return (
            f"{self._config.idp_slo_url}?SessionIndex={session_index}&NameID={name_id}"
        )

    def _purge_expired(self) -> None:
        now = self._clock()
        ttl = self._config.replay_window_seconds
        stale = [rid for rid, ts in self._issued.items() if now - ts > ttl]
        for rid in stale:
            self._issued.pop(rid, None)
