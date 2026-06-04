"""Тесты :class:`SamlBackend` (V15 S6 DoD).

Не требуют ``python3-saml`` C-extension'а — тестируем контракт класса
(replay-defence, expiry, redirect URL composition) с инжектируемыми
``validator`` и ``clock``.
"""

from __future__ import annotations

import pytest

from src.backend.core.auth.saml_backend import (
    SamlAuthResult,
    SamlBackend,
    SamlConfig,
    SamlError,
)


def _config() -> SamlConfig:
    return SamlConfig(
        sp_entity_id="https://sp.example.com/metadata",
        sp_acs_url="https://sp.example.com/acs",
        sp_sls_url="https://sp.example.com/sls",
        sp_x509_cert="-----SP CERT-----",
        sp_private_key="-----SP KEY-----",
        idp_entity_id="https://idp.example.com",
        idp_sso_url="https://idp.example.com/sso",
        idp_slo_url="https://idp.example.com/slo",
        idp_x509_cert="-----IDP CERT-----",
        replay_window_seconds=60.0,
    )


def _backend(*, now: list[float] | None = None) -> SamlBackend:
    """Helper: backend с подменяемым clock-listом."""
    times = now or [1000.0]
    counter = {"i": 0}

    def clock() -> float:
        i = counter["i"]
        counter["i"] = min(i + 1, len(times) - 1)
        return times[i]

    nonces = iter(["req-1", "req-2", "req-3"])
    return SamlBackend(
        config=_config(), clock=clock, nonce_factory=lambda: next(nonces)
    )


def test_build_login_redirect_returns_url_and_request_id() -> None:
    backend = _backend()
    url, request_id = backend.build_login_redirect_url(relay_state="dashboard")
    assert "https://idp.example.com/sso" in url
    assert "RelayState=dashboard" in url
    assert request_id == "req-1"


def test_process_response_validates_request_id() -> None:
    """Замыкание ``validator`` вызывается ровно при success."""
    backend = _backend()
    _, rid = backend.build_login_redirect_url()

    expected = SamlAuthResult(
        principal="alice@example.com",
        attributes={"email": "alice@example.com"},
        session_index="sess-1",
    )
    result = backend.process_saml_response(request_id=rid, validator=lambda: expected)
    assert result == expected


def test_replay_defence_blocks_reuse_of_request_id() -> None:
    """Повторное использование ``request_id`` → :class:`SamlError`."""
    backend = _backend()
    _, rid = backend.build_login_redirect_url()
    backend.process_saml_response(
        request_id=rid,
        validator=lambda: SamlAuthResult(principal="alice", attributes={}),
    )
    with pytest.raises(SamlError) as exc_info:
        backend.process_saml_response(
            request_id=rid,
            validator=lambda: SamlAuthResult(principal="alice", attributes={}),
        )
    assert "replay" in exc_info.value.args[0].lower()


def test_unknown_request_id_rejected() -> None:
    backend = _backend()
    with pytest.raises(SamlError):
        backend.process_saml_response(
            request_id="never-issued",
            validator=lambda: SamlAuthResult(principal="alice", attributes={}),
        )


def test_expired_request_id_rejected() -> None:
    """``InResponseTo`` со старше ``replay_window_seconds`` → fail."""
    # Clock: build (1000) → process (1000+999, expired).
    backend = _backend(now=[1000.0, 1000.0, 1000.0 + 9999])
    _, rid = backend.build_login_redirect_url()
    with pytest.raises(SamlError) as exc_info:
        backend.process_saml_response(
            request_id=rid,
            validator=lambda: SamlAuthResult(principal="alice", attributes={}),
        )
    assert "expired" in exc_info.value.args[0]


def test_validator_failure_wrapped_in_saml_error() -> None:
    backend = _backend()
    _, rid = backend.build_login_redirect_url()

    def bad() -> SamlAuthResult:
        raise ValueError("signature mismatch")

    with pytest.raises(SamlError) as exc_info:
        backend.process_saml_response(request_id=rid, validator=bad)
    assert "signature mismatch" in exc_info.value.args[0]


def test_logout_url_composition() -> None:
    backend = _backend()
    url = backend.build_logout_redirect_url(
        session_index="sess-99", name_id="alice@example.com"
    )
    assert url.startswith("https://idp.example.com/slo")
    assert "SessionIndex=sess-99" in url
    assert "NameID=alice%40example.com" in url or "NameID=alice@example.com" in url


def test_is_available_no_dependency() -> None:
    """``is_available`` возвращает False когда python3-saml не установлен."""
    backend = _backend()
    # В тестовом окружении xmlsec/python3-saml не установлены.
    assert backend.is_available() is False
