"""Smoke-тесты mTLS fixture store (Sprint 3 W1 К1).

Проверяет, что :mod:`testkit.mtls_fixtures` корректно генерирует
самоподписанные CA + server/client cert chain и что cert'ы парсятся
через :class:`MtlsBackend` без ошибок.

Тесты:
    1. ``test_cert_generation_produces_valid_pem`` — ca/server/client
       PEM содержат корректные ``BEGIN CERTIFICATE``/``BEGIN PRIVATE KEY``
       блоки и SHA-256 fingerprint совпадает с ``MtlsBackend``-парсингом.
    2. ``test_mtls_backend_accepts_client_cert`` — :class:`MtlsBackend`
       принимает сгенерированный client cert через
       ``default_cryptography_parser``.
"""

from __future__ import annotations

import pytest

from src.backend.core.auth.mtls_backend import (
    MtlsBackend,
    MtlsConfig,
    default_cryptography_parser,
)
from testkit.mtls_fixtures import (
    CertChain,
    ca_cert,  # noqa: F401 — re-export фикстура.
    client_cert_chain,  # noqa: F401
    server_cert_chain,  # noqa: F401
)


class _FakeRequest:
    """Минимальный stub :class:`Request` для :meth:`MtlsBackend.verify`."""

    def __init__(self, headers: dict[str, str]) -> None:
        self._headers = headers

    @property
    def headers(self) -> object:
        store = self._headers

        class _H:
            def get(self, key: str, default: object | None = None) -> object | None:
                return store.get(key, default)

        return _H()


def test_cert_generation_produces_valid_pem(
    ca_cert: CertChain,  # noqa: F811 — pytest fixture override.
    server_cert_chain: CertChain,  # noqa: F811
    client_cert_chain: CertChain,  # noqa: F811
) -> None:
    """CA/server/client cert'ы содержат корректные PEM-blocks и fingerprint."""
    for chain in (ca_cert, server_cert_chain, client_cert_chain):
        assert chain.cert_pem.startswith(b"-----BEGIN CERTIFICATE-----")
        assert chain.cert_pem.rstrip().endswith(b"-----END CERTIFICATE-----")
        assert b"-----BEGIN PRIVATE KEY-----" in chain.key_pem
        assert len(chain.fingerprint_sha256) == 64  # SHA-256 hex = 64 chars.
        # Subject CN кодируется в PEM напрямую — детект через парсер
        # выполняется в следующем тесте.
        assert chain.subject_cn

    # Client/server cert'ы подписаны одним CA — fingerprint'ы разные.
    assert server_cert_chain.fingerprint_sha256 != client_cert_chain.fingerprint_sha256
    assert ca_cert.fingerprint_sha256 != client_cert_chain.fingerprint_sha256


def test_mtls_backend_accepts_client_cert(
    client_cert_chain: CertChain,  # noqa: F811
) -> None:
    """:class:`MtlsBackend` парсит client cert и возвращает principal.

    Подтверждает, что :func:`default_cryptography_parser` корректно
    извлекает ``subject_cn`` и SHA-256 fingerprint из тестового cert'а,
    сгенерированного фикстурой.
    """
    try:
        parser = default_cryptography_parser()
    except RuntimeError:
        pytest.skip("cryptography is not installed (required for mTLS fixture)")

    backend = MtlsBackend(config=MtlsConfig(), cert_parser=parser)
    request = _FakeRequest(
        {"X-Client-Cert": client_cert_chain.cert_pem.decode("utf-8")}
    )

    result = backend.verify(request)
    assert result is not None
    assert result["principal"] == "test-client"
    assert result["fingerprint"].lower() == client_cert_chain.fingerprint_sha256.lower()
    assert result["issuer"] == "test-ca"
