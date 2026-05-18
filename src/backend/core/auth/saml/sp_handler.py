"""SAML SP-initiated orchestrator (Sprint 9 K1 W1).

Класс :class:`SamlSpHandler` инкапсулирует FastAPI-агностичный flow:

#. ``initiate_login(...)`` — генерация SP-initiated redirect URL + relay-state;
#. ``consume_acs(...)`` — обработка SAMLResponse от IdP, возврат
   :class:`SamlAuthResult` либо :class:`SamlError`.

Зависит только от :class:`SamlBackend` (низкоуровневый). FastAPI endpoint
:mod:`entrypoints.api.v1.endpoints.auth_saml` использует этот handler.
"""

from __future__ import annotations

from dataclasses import dataclass

from src.backend.core.auth.saml_backend import (
    SamlAuthResult,
    SamlBackend,
    SamlError,
)

__all__ = ("SamlSpHandler", "SpInitiatedLoginResult")


@dataclass(frozen=True, slots=True)
class SpInitiatedLoginResult:
    """Результат инициации SP-initiated login.

    Attributes:
        redirect_url: URL для 302 redirect клиента к IdP.
        request_id: AuthnRequest ID — нужен на ACS для matching
            ``InResponseTo`` (replay-defence).
        relay_state: RelayState — будет вернут IdP клиенту, используется
            для пост-логин redirect на изначальную страницу.
    """

    redirect_url: str
    request_id: str
    relay_state: str


class SamlSpHandler:
    """Высокоуровневый orchestrator SP-initiated SSO.

    Объединяет :class:`SamlBackend` с relay-state management и default
    post-login redirect.

    Args:
        backend: Низкоуровневый :class:`SamlBackend`.
        default_post_login_url: куда редиректить если RelayState пуст
            (default ``"/"``).
    """

    def __init__(
        self,
        *,
        backend: SamlBackend,
        default_post_login_url: str = "/",
    ) -> None:
        self._backend = backend
        self._default_post_login = default_post_login_url

    def initiate_login(
        self,
        *,
        return_to: str | None = None,
    ) -> SpInitiatedLoginResult:
        """Сгенерировать SSO-redirect URL.

        Args:
            return_to: куда вернуть пользователя после login. Encoded
                в RelayState и проверяется на same-origin в ACS.

        Returns:
            :class:`SpInitiatedLoginResult`.
        """
        relay_state = return_to or self._default_post_login
        url, request_id = self._backend.build_login_redirect_url(
            relay_state=relay_state
        )
        return SpInitiatedLoginResult(
            redirect_url=url,
            request_id=request_id,
            relay_state=relay_state,
        )

    def consume_acs(
        self,
        *,
        request_id: str,
        validator_factory,
    ) -> SamlAuthResult:
        """Обработать SAMLResponse в ACS-endpoint.

        Args:
            request_id: ``InResponseTo`` из SAMLResponse.
            validator_factory: Зависимость-фабрика, возвращающая
                :class:`SamlAuthResult` (обёртка над
                ``OneLogin_Saml2_Auth.process_response``). Инъекция
                делает handler тестируемым без xmlsec.

        Raises:
            SamlError: при replay-attack, expired token, или невалидной
                подписи.
        """
        return self._backend.process_saml_response(
            request_id=request_id,
            validator=validator_factory,
        )

    def is_available(self) -> bool:
        """Прокси к :meth:`SamlBackend.is_available`."""
        return self._backend.is_available()
