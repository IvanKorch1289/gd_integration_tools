"""Тесты :class:`MtlsBackend` (V15 S2 DoD)."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import pytest

from src.backend.core.auth.mtls_backend import (
    MtlsBackend,
    MtlsConfig,
    MtlsVerificationError,
    ParsedClientCert,
)


@dataclass(frozen=True)
class _FakeRequest:
    """Минимальный stub :class:`Request` (только ``.headers.get(...)``)."""

    _headers: dict[str, str]

    @property
    def headers(self) -> Any:
        store = self._headers

        class _H:
            def get(self, key: str, default: Any = None) -> Any:
                return store.get(key, default)

        return _H()


def _request(**headers: str) -> _FakeRequest:
    return _FakeRequest(_headers=headers)


def test_no_cert_returns_none() -> None:
    """Без headers и PEM — backend возвращает ``None`` (не аутентифицирован)."""
    backend = MtlsBackend()
    assert backend.verify(_request()) is None


def test_headers_only_pass_through() -> None:
    """Если PEM не передан, fingerprint+subject принимаются."""
    backend = MtlsBackend()
    result = backend.verify(
        _request(
            **{
                "X-Client-Cert-Fingerprint": "ABCDEF",
                "X-Client-Cert-Subject": "CN=alice",
            }
        )
    )
    assert result is not None
    assert result["principal"] == "CN=alice"
    assert result["fingerprint"] == "abcdef"


def test_pem_validation_rejects_expired() -> None:
    """PEM expired → :class:`MtlsVerificationError`."""

    def parser(_pem: bytes) -> ParsedClientCert:
        return ParsedClientCert(
            subject_cn="alice",
            subject_ou=None,
            not_before=0,
            not_after=100,
            fingerprint_sha256="aa",
        )

    backend = MtlsBackend(cert_parser=parser, current_time=lambda: 1_000_000.0)
    with pytest.raises(MtlsVerificationError) as exc_info:
        backend.verify(_request(**{"X-Client-Cert": "PEM"}))
    assert "expired" in exc_info.value.reason


def test_pem_validation_rejects_not_yet_valid() -> None:
    def parser(_pem: bytes) -> ParsedClientCert:
        return ParsedClientCert(
            subject_cn="alice",
            subject_ou=None,
            not_before=2_000_000,
            not_after=3_000_000,
            fingerprint_sha256="aa",
        )

    backend = MtlsBackend(cert_parser=parser, current_time=lambda: 1_000_000.0)
    with pytest.raises(MtlsVerificationError) as exc_info:
        backend.verify(_request(**{"X-Client-Cert": "PEM"}))
    assert "not yet valid" in exc_info.value.reason


def test_pem_validation_passes_valid_cert() -> None:
    def parser(_pem: bytes) -> ParsedClientCert:
        return ParsedClientCert(
            subject_cn="alice",
            subject_ou="ENG",
            not_before=0,
            not_after=10**12,
            fingerprint_sha256="DEADBEEF",
            issuer_cn="Internal-CA",
        )

    backend = MtlsBackend(cert_parser=parser, current_time=lambda: 100.0)
    result = backend.verify(_request(**{"X-Client-Cert": "PEM"}))
    assert result is not None
    assert result["principal"] == "alice"
    assert result["fingerprint"] == "deadbeef"
    assert result["issuer"] == "Internal-CA"


def test_fingerprint_pinning_blocks_unknown_cert() -> None:
    """allowed_fingerprints whitelist блокирует чужой fp."""
    config = MtlsConfig(allowed_fingerprints=frozenset({"abc"}))
    backend = MtlsBackend(config=config)
    with pytest.raises(MtlsVerificationError) as exc_info:
        backend.verify(
            _request(
                **{
                    "X-Client-Cert-Fingerprint": "BAD",
                    "X-Client-Cert-Subject": "CN=evil",
                }
            )
        )
    assert "pinned" in exc_info.value.reason


def test_issuer_pinning_blocks_wrong_ca() -> None:
    """allowed_issuer_cns whitelist блокирует cert от чужого CA."""
    config = MtlsConfig(allowed_issuer_cns=frozenset({"trusted-ca"}))

    def parser(_pem: bytes) -> ParsedClientCert:
        return ParsedClientCert(
            subject_cn="alice",
            subject_ou=None,
            not_before=0,
            not_after=10**12,
            fingerprint_sha256="aa",
            issuer_cn="evil-ca",
        )

    backend = MtlsBackend(
        config=config, cert_parser=parser, current_time=lambda: 100.0
    )
    with pytest.raises(MtlsVerificationError) as exc_info:
        backend.verify(_request(**{"X-Client-Cert": "PEM"}))
    assert "issuer" in exc_info.value.reason


def test_require_pem_body_blocks_headers_only() -> None:
    """``require_pem_body=True`` отвергает headers-only клиентов."""
    config = MtlsConfig(require_pem_body=True)
    backend = MtlsBackend(config=config)
    with pytest.raises(MtlsVerificationError) as exc_info:
        backend.verify(_request(**{"X-Client-Cert-Fingerprint": "abc"}))
    assert "PEM body required" in exc_info.value.reason
