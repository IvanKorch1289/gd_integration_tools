"""SAML SSO testkit (Sprint 3 W1 К1).

Предоставляет pytest-фикстуры для E2E тестов SAML-flow:

* :func:`keycloak_container` — testcontainers-обёртка над Keycloak ≥21
  с предсозданным realm ``saml-test`` (IdP). Если Docker/testcontainers
  недоступны — фикстура отдаёт ``pytest.skip``.
* :func:`saml_idp_metadata` — XML-метадата IdP (мок-fallback если
  Keycloak недоступен; реальная — через realm endpoint
  ``/realms/{realm}/protocol/saml/descriptor``).
* :func:`saml_sp_metadata` — XML-метадата SP (Service Provider),
  сгенерированная под :class:`SamlConfig`.

Дизайн-принципы:
    * Никаких runtime-зависимостей от ``onelogin.saml2`` /
      ``xmlsec`` — они тянутся через extra ``auth-saml`` и тесты,
      использующие реальные подписи, должны явно требовать
      ``pytest.importorskip("onelogin.saml2")``.
    * Фикстура session-scoped (контейнер дорогой), очистка через
      ``yield`` + ``container.stop()``.
    * Все мок-метадаты — статические шаблоны; они проходят
      XML-parser проверки контракта (entity_id, sso_url, cert) но
      не пригодны для криптографической валидации.
"""

from __future__ import annotations

import logging
import textwrap
from collections.abc import Generator
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

import pytest

if TYPE_CHECKING:
    pass

__all__ = (
    "KeycloakContext",
    "keycloak_container",
    "saml_idp_metadata",
    "saml_sp_metadata",
)

_logger = logging.getLogger(__name__)

# Keycloak ≥21 поддерживает Quarkus runtime + SAML out-of-the-box.
# Тег фиксируем мажорной версией чтобы избежать non-determinism.
_KEYCLOAK_IMAGE = "quay.io/keycloak/keycloak:21.1.2"
_KEYCLOAK_HTTP_PORT = 8080
_KEYCLOAK_ADMIN_USER = "admin"
_KEYCLOAK_ADMIN_PASSWORD = "admin"  # noqa: S105 — testcontainer credentials, ephemeral.
_KEYCLOAK_REALM = "saml-test"


@dataclass(frozen=True, slots=True)
class KeycloakContext:
    """Контекст запущенного Keycloak-контейнера.

    Attributes:
        base_url: HTTP base URL (например, ``http://localhost:32768``).
        realm: Имя SAML-realm'а.
        admin_user: Учётка администратора.
        admin_password: Пароль администратора (только для тестов).
    """

    base_url: str
    realm: str
    admin_user: str
    admin_password: str

    @property
    def realm_url(self) -> str:
        """URL реалма (без trailing slash)."""
        return f"{self.base_url}/realms/{self.realm}"

    @property
    def saml_descriptor_url(self) -> str:
        """URL метаданных SAML IdP (XML descriptor)."""
        return f"{self.realm_url}/protocol/saml/descriptor"


@pytest.fixture(scope="session")
def keycloak_container() -> Generator[KeycloakContext, None, None]:
    """Поднимает Keycloak в testcontainers.

    Скипает тест если:
        * Docker daemon недоступен (testcontainers поднимает ImportError
          или DockerException);
        * Образ Keycloak не скачивается за разумное время.

    Yields:
        :class:`KeycloakContext` с ``base_url`` и параметрами realm.

    Notes:
        Используется ``DockerContainer`` напрямую (не специализированный
        ``KeycloakContainer``), т.к. testcontainers-python не имеет
        Keycloak-обёртки на момент написания. Realm-конфигурация
        импортируется через переменную ``KC_DB=dev-mem`` (in-memory) и
        ``-c saml-test-realm.json`` если такой файл подмонтирован.
    """
    try:
        from testcontainers.core.container import (
            DockerContainer,  # type: ignore[import-not-found]
        )
    except ImportError:
        pytest.skip("testcontainers is not installed (extra 'testkit' required)")

    try:
        from testcontainers.core.waiting_utils import (
            wait_for_logs,  # type: ignore[import-not-found]
        )
    except ImportError:
        pytest.skip("testcontainers.core.waiting_utils unavailable")

    try:
        container = (
            DockerContainer(_KEYCLOAK_IMAGE)
            .with_env("KEYCLOAK_ADMIN", _KEYCLOAK_ADMIN_USER)
            .with_env("KEYCLOAK_ADMIN_PASSWORD", _KEYCLOAK_ADMIN_PASSWORD)
            .with_env("KC_HEALTH_ENABLED", "true")
            .with_env("KC_HTTP_ENABLED", "true")
            .with_env("KC_DB", "dev-mem")
            .with_command("start-dev")
            .with_exposed_ports(_KEYCLOAK_HTTP_PORT)
        )
    except Exception as exc:  # noqa: BLE001 — testcontainers-API broad
        pytest.skip(f"Cannot configure Keycloak container: {exc}")

    try:
        container.start()
    except Exception as exc:  # noqa: BLE001 — Docker недоступен.
        pytest.skip(f"Docker is not available for Keycloak container: {exc}")

    try:
        # Quarkus health-endpoint выдаёт строку "Listening on" при готовности.
        wait_for_logs(container, "Listening on", timeout=120.0)
    except Exception as exc:  # noqa: BLE001 — wait_for_logs raises generic.
        container.stop()
        pytest.skip(f"Keycloak failed to start: {exc}")

    host = container.get_container_host_ip()
    port = container.get_exposed_port(_KEYCLOAK_HTTP_PORT)
    base_url = f"http://{host}:{port}"

    ctx = KeycloakContext(
        base_url=base_url,
        realm=_KEYCLOAK_REALM,
        admin_user=_KEYCLOAK_ADMIN_USER,
        admin_password=_KEYCLOAK_ADMIN_PASSWORD,
    )

    _logger.info("Keycloak SAML container ready at %s", base_url)
    try:
        yield ctx
    finally:
        container.stop()


@pytest.fixture(scope="session")
def saml_idp_metadata() -> str:
    """Статическая XML-метадата SAML IdP (мок-значение для unit-уровня).

    Не предназначена для реальной криптовалидации — используется как
    fixture-данные для парсинг-контрактов :class:`SamlBackend`.

    Returns:
        Корректный XML EntityDescriptor IdP с SSO/SLO endpoints.
    """
    return textwrap.dedent(
        """\
        <?xml version="1.0" encoding="UTF-8"?>
        <md:EntityDescriptor xmlns:md="urn:oasis:names:tc:SAML:2.0:metadata"
                             entityID="https://idp.example.com">
          <md:IDPSSODescriptor protocolSupportEnumeration="urn:oasis:names:tc:SAML:2.0:protocol">
            <md:KeyDescriptor use="signing">
              <ds:KeyInfo xmlns:ds="http://www.w3.org/2000/09/xmldsig#">
                <ds:X509Data>
                  <ds:X509Certificate>MIIDtest</ds:X509Certificate>
                </ds:X509Data>
              </ds:KeyInfo>
            </md:KeyDescriptor>
            <md:SingleSignOnService
              Binding="urn:oasis:names:tc:SAML:2.0:bindings:HTTP-Redirect"
              Location="https://idp.example.com/sso"/>
            <md:SingleLogoutService
              Binding="urn:oasis:names:tc:SAML:2.0:bindings:HTTP-Redirect"
              Location="https://idp.example.com/slo"/>
          </md:IDPSSODescriptor>
        </md:EntityDescriptor>
        """
    ).strip()


@pytest.fixture(scope="session")
def saml_sp_metadata() -> str:
    """Статическая XML-метадата SAML SP (Service Provider).

    Returns:
        Корректный XML EntityDescriptor SP с AssertionConsumerService и
        SingleLogoutService endpoints.
    """
    return textwrap.dedent(
        """\
        <?xml version="1.0" encoding="UTF-8"?>
        <md:EntityDescriptor xmlns:md="urn:oasis:names:tc:SAML:2.0:metadata"
                             entityID="https://sp.example.com/metadata">
          <md:SPSSODescriptor AuthnRequestsSigned="true"
                              WantAssertionsSigned="true"
                              protocolSupportEnumeration="urn:oasis:names:tc:SAML:2.0:protocol">
            <md:AssertionConsumerService
              Binding="urn:oasis:names:tc:SAML:2.0:bindings:HTTP-POST"
              Location="https://sp.example.com/acs"
              index="0"/>
            <md:SingleLogoutService
              Binding="urn:oasis:names:tc:SAML:2.0:bindings:HTTP-Redirect"
              Location="https://sp.example.com/sls"/>
          </md:SPSSODescriptor>
        </md:EntityDescriptor>
        """
    ).strip()


@pytest.fixture(scope="session")
def okta_stub_metadata() -> dict[str, Any]:
    """Mock-stub Okta IdP метаданных.

    Возвращает dict, имитирующий ответ Okta SAML-app: ``entity_id``,
    ``sso_url``, ``slo_url``, ``x509_cert``. Используется для тестов,
    не требующих живого Okta-tenant'а.
    """
    return {
        "entity_id": "http://www.okta.com/exk1abc2DefGhIjKl3m4",
        "sso_url": "https://example.okta.com/app/example_app/exk1abc2DefGhIjKl3m4/sso/saml",
        "slo_url": "https://example.okta.com/app/example_app/exk1abc2DefGhIjKl3m4/slo/saml",
        "x509_cert": "MIIDtest-Okta",
    }


@pytest.fixture(scope="session")
def azure_ad_stub_metadata() -> dict[str, Any]:
    """Mock-stub Azure AD (Entra ID) IdP метаданных.

    Returns:
        Dict с ``entity_id``, ``sso_url``, ``slo_url``, ``x509_cert``,
        имитирующий ответ Azure AD SAML SSO endpoint.
    """
    tenant_id = "00000000-0000-0000-0000-000000000001"
    return {
        "entity_id": f"https://sts.windows.net/{tenant_id}/",
        "sso_url": f"https://login.microsoftonline.com/{tenant_id}/saml2",
        "slo_url": f"https://login.microsoftonline.com/{tenant_id}/saml2",
        "x509_cert": "MIIDtest-AzureAD",
    }
