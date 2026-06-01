"""Unit-тесты SP-initiated SAML flow (Sprint 9 K1 W1).

Без внешних зависимостей (``python3-saml`` не обязательно — validator
инжектится).
"""

from __future__ import annotations

import pytest

from src.backend.core.auth.saml import (
    SamlAuthResult,
    SamlBackend,
    SamlConfig,
    SamlError,
    SamlSpHandler,
)


@pytest.fixture
def config() -> SamlConfig:
    return SamlConfig(
        sp_entity_id="urn:test:sp",
        sp_acs_url="https://sp.test/acs",
        sp_x509_cert="-----BEGIN CERT-----stub-----END CERT-----",
        sp_private_key="-----BEGIN PRIVATE-----stub-----END PRIVATE-----",
        idp_entity_id="urn:test:idp",
        idp_sso_url="https://idp.test/sso",
        idp_x509_cert="-----BEGIN CERT-----idp-----END CERT-----",
        replay_window_seconds=60.0,
    )


@pytest.fixture
def handler(config: SamlConfig) -> SamlSpHandler:
    backend = SamlBackend(config=config)
    return SamlSpHandler(backend=backend, default_post_login_url="/dashboard")


def test_initiate_login_returns_redirect_and_request_id(
    handler: SamlSpHandler,
) -> None:
    result = handler.initiate_login()
    assert result.redirect_url.startswith("https://idp.test/sso?SAMLRequest=")
    assert result.request_id
    assert result.relay_state == "/dashboard"


def test_initiate_login_with_return_to(handler: SamlSpHandler) -> None:
    result = handler.initiate_login(return_to="/orders/42")
    assert result.relay_state == "/orders/42"
    assert "/orders/42" in result.redirect_url


def test_consume_acs_replay_defence(handler: SamlSpHandler) -> None:
    login = handler.initiate_login()
    auth_result = SamlAuthResult(
        principal="user@bank.local",
        attributes={"email": "user@bank.local"},
        session_index="idx-1",
    )

    # Первый ACS-вызов проходит
    out = handler.consume_acs(
        request_id=login.request_id,
        validator_factory=lambda: auth_result,
    )
    assert out.principal == "user@bank.local"

    # Повторное использование того же request_id отклоняется
    with pytest.raises(SamlError, match="replay"):
        handler.consume_acs(
            request_id=login.request_id,
            validator_factory=lambda: auth_result,
        )


def test_consume_acs_unknown_request_id_rejected(handler: SamlSpHandler) -> None:
    with pytest.raises(SamlError, match="unknown"):
        handler.consume_acs(
            request_id="never-issued",
            validator_factory=lambda: SamlAuthResult(
                principal="x", attributes={}, session_index=None
            ),
        )


def test_consume_acs_expired_window(config: SamlConfig) -> None:
    # Issue в t=0, process в t=1000 → > 60s TTL → expired
    # (build вызывает clock дважды: issue + _purge_expired)
    times = iter([0.0, 0.0, 1000.0])

    def fake_clock() -> float:
        return next(times)

    backend = SamlBackend(config=config, clock=fake_clock)
    _, request_id = backend.build_login_redirect_url()
    with pytest.raises(SamlError, match="expired"):
        backend.process_saml_response(
            request_id=request_id,
            validator=lambda: SamlAuthResult(
                principal="x", attributes={}, session_index=None
            ),
        )


def test_validator_exception_wrapped_as_saml_error(
    handler: SamlSpHandler,
) -> None:
    login = handler.initiate_login()

    def _bad_validator() -> SamlAuthResult:
        raise ValueError("xmlsec error")

    with pytest.raises(SamlError, match="validation failed"):
        handler.consume_acs(
            request_id=login.request_id,
            validator_factory=_bad_validator,
        )


def test_is_available_proxies_backend(handler: SamlSpHandler) -> None:
    # is_available возвращает bool в зависимости от python3-saml
    # (lazy-import).
    assert isinstance(handler.is_available(), bool)
