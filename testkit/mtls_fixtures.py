"""mTLS testkit (Sprint 3 W1 К1).

Генерирует self-signed CA + server-cert + client-cert chain для
интеграционных тестов mTLS-handshake. Использует ``cryptography``
(pyca) X.509 builder.

Размер ключа специально **уменьшен до 1024 bit** (только для тестов!)
ради скорости генерации — production-CA должен быть ≥2048 bit, как
указано в :class:`MtlsConfig`. Не использовать эти fixtures для
production deployment.

Фикстуры:
    * :func:`ca_cert` — корневой CA (RSA-1024 self-signed).
    * :func:`server_cert_chain` — сервер cert+key подписанный CA.
    * :func:`client_cert_chain` — клиент cert+key подписанный тем же CA.
    * :func:`mtls_httpx_client` — :class:`httpx.AsyncClient` настроенный
      с ``verify=ca_pem`` и ``cert=(client_pem, client_key_pem)``.

Все фикстуры session-scoped — генерация cert'ов дорогая (≈200ms).
"""

from __future__ import annotations

import datetime as _dt
from collections.abc import Generator
from dataclasses import dataclass

import pytest

__all__ = (
    "CertChain",
    "ca_cert",
    "client_cert_chain",
    "mtls_httpx_client",
    "server_cert_chain",
)


@dataclass(frozen=True, slots=True)
class CertChain:
    """Контейнер для cert + private key в PEM-формате.

    Attributes:
        cert_pem: PEM-encoded X.509 certificate.
        key_pem: PEM-encoded RSA private key (PKCS#8, unencrypted).
        subject_cn: Common Name, для удобства assert'ов.
        fingerprint_sha256: SHA-256 fingerprint (hex, lowercase).
    """

    cert_pem: bytes
    key_pem: bytes
    subject_cn: str
    fingerprint_sha256: str


def _generate_key_pair() -> tuple[object, bytes]:
    """Генерирует RSA-1024 keypair и возвращает (cryptography private_key, PKCS#8 PEM)."""
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric import rsa

    private_key = rsa.generate_private_key(public_exponent=65537, key_size=1024)  # noqa: S505 — test fixtures only; ускоряет генерацию (см. CertChain docstring)
    pem = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    return private_key, pem


def _build_cert(
    *,
    subject_cn: str,
    issuer_cn: str,
    public_key: object,
    signing_key: object,
    is_ca: bool,
) -> object:
    """Строит x509-cert с минимальным набором extensions (BasicConstraints).

    Args:
        subject_cn: Subject Common Name.
        issuer_cn: Issuer Common Name (для self-signed = subject).
        public_key: Public key владельца cert'а.
        signing_key: Private key подписанта (для CA = его собственный).
        is_ca: ``True`` → BasicConstraints CA=true (PathLength=0 для intermediate).

    Returns:
        :class:`cryptography.x509.Certificate`.
    """
    from cryptography import x509
    from cryptography.hazmat.primitives import hashes
    from cryptography.x509.oid import NameOID

    subject = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, subject_cn)])
    issuer = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, issuer_cn)])
    now = _dt.datetime.now(tz=_dt.UTC)
    builder = (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(public_key)
        .serial_number(x509.random_serial_number())
        .not_valid_before(now - _dt.timedelta(minutes=1))
        .not_valid_after(now + _dt.timedelta(days=1))
        .add_extension(x509.BasicConstraints(ca=is_ca, path_length=None), critical=True)
    )
    return builder.sign(private_key=signing_key, algorithm=hashes.SHA256())


def _cert_to_chain(cert: object, key_pem: bytes, *, subject_cn: str) -> CertChain:
    """Сериализует cert + key в :class:`CertChain`."""
    from cryptography.hazmat.primitives import hashes, serialization

    cert_pem = cert.public_bytes(serialization.Encoding.PEM)  # type: ignore[attr-defined]
    fingerprint = cert.fingerprint(hashes.SHA256()).hex()  # type: ignore[attr-defined]
    return CertChain(
        cert_pem=cert_pem,
        key_pem=key_pem,
        subject_cn=subject_cn,
        fingerprint_sha256=fingerprint,
    )


@pytest.fixture(scope="session")
def ca_cert() -> CertChain:
    """Корневой self-signed CA cert.

    Returns:
        :class:`CertChain` с CN=``test-ca``.
    """
    pytest.importorskip("cryptography")
    ca_key_obj, ca_key_pem = _generate_key_pair()
    cert = _build_cert(
        subject_cn="test-ca",
        issuer_cn="test-ca",
        public_key=ca_key_obj.public_key(),  # type: ignore[attr-defined]
        signing_key=ca_key_obj,
        is_ca=True,
    )
    return _cert_to_chain(cert, ca_key_pem, subject_cn="test-ca")


@pytest.fixture(scope="session")
def _ca_keypair(ca_cert: CertChain) -> tuple[object, object]:
    """Internal: возвращает (ca_cert_obj, ca_key_obj) для подписи дочерних cert'ов."""
    from cryptography import x509
    from cryptography.hazmat.primitives import serialization

    ca_cert_obj = x509.load_pem_x509_certificate(ca_cert.cert_pem)
    ca_key_obj = serialization.load_pem_private_key(ca_cert.key_pem, password=None)
    return ca_cert_obj, ca_key_obj


@pytest.fixture(scope="session")
def server_cert_chain(_ca_keypair: tuple[object, object]) -> CertChain:
    """Server cert подписанный CA.

    CN=``test-server``. Подписывается ключом ``ca_cert`` (тот же CA).
    """
    _, ca_key_obj = _ca_keypair
    server_key_obj, server_key_pem = _generate_key_pair()
    cert = _build_cert(
        subject_cn="test-server",
        issuer_cn="test-ca",
        public_key=server_key_obj.public_key(),  # type: ignore[attr-defined]
        signing_key=ca_key_obj,
        is_ca=False,
    )
    return _cert_to_chain(cert, server_key_pem, subject_cn="test-server")


@pytest.fixture(scope="session")
def client_cert_chain(_ca_keypair: tuple[object, object]) -> CertChain:
    """Client cert подписанный CA.

    CN=``test-client``. Используется на стороне ``httpx.AsyncClient.cert``.
    """
    _, ca_key_obj = _ca_keypair
    client_key_obj, client_key_pem = _generate_key_pair()
    cert = _build_cert(
        subject_cn="test-client",
        issuer_cn="test-ca",
        public_key=client_key_obj.public_key(),  # type: ignore[attr-defined]
        signing_key=ca_key_obj,
        is_ca=False,
    )
    return _cert_to_chain(cert, client_key_pem, subject_cn="test-client")


@pytest.fixture
def mtls_httpx_client(
    tmp_path_factory: pytest.TempPathFactory,
    ca_cert: CertChain,
    client_cert_chain: CertChain,
) -> Generator[object, None, None]:
    """:class:`httpx.AsyncClient` сконфигурированный с mTLS cert chain.

    Args:
        tmp_path_factory: pytest tmp_path (для записи PEM в файлы —
            httpx требует именно paths, а не bytes).
        ca_cert: Trusted CA bundle.
        client_cert_chain: Client cert+key.

    Yields:
        :class:`httpx.AsyncClient` готовый к ``async with``-использованию
        (caller вызывает ``await client.aclose()`` сам, либо использует
        в test'е через ``async with``).
    """
    httpx = pytest.importorskip("httpx")

    base = tmp_path_factory.mktemp("mtls")
    ca_path = base / "ca.pem"
    client_cert_path = base / "client.pem"
    client_key_path = base / "client.key"

    ca_path.write_bytes(ca_cert.cert_pem)
    client_cert_path.write_bytes(client_cert_chain.cert_pem)
    client_key_path.write_bytes(client_cert_chain.key_pem)

    client = httpx.AsyncClient(
        verify=str(ca_path),
        cert=(str(client_cert_path), str(client_key_path)),
        timeout=10.0,
    )
    try:
        yield client
    finally:
        # Caller должен закрыть client сам через `await client.aclose()`,
        # но для безопасности fixture закрывает синхронно (без await).
        # httpx.AsyncClient допускает .close() для transport-cleanup.
        # noinspection PyBroadException
        try:
            transport = getattr(client, "_transport", None)
            if transport is not None and hasattr(transport, "close"):
                transport.close()
        except Exception as exc:  # noqa: BLE001 — best-effort cleanup в test-fixture
            # Логируем но не падаем — test-fixture не должна разрушать teardown.
            import logging as _logging  # noqa: PLC0415

            _logging.getLogger(__name__).debug(
                "mtls fixture transport cleanup ignored: %s", exc
            )
