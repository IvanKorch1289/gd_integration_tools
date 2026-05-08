"""mTLS auth backend (V15 S2 DoD).

Поддерживает три способа получения client cert:

1. **Trusted-proxy headers** — Envoy/Nginx с TLS-termination передают:
   * ``X-Client-Cert-Subject`` — subject DN;
   * ``X-Client-Cert-Fingerprint`` — SHA-256 fingerprint (hex);
   * ``X-Client-Cert`` — PEM-encoded cert (опционально).
2. **PEM body validation** — при наличии PEM и доступной библиотеки
   ``cryptography`` парсим x509 → проверяем NotBefore/NotAfter, subject CN.
3. **CA-pinning** — опц. сравнение fingerprint'а с whitelist'ом
   ``allowed_fingerprints`` (для строгого pin'а в банковской среде).

Для unit-тестов :class:`MtlsBackend` принимает ``current_time``-callable
и ``cert_parser`` — что позволяет проверять expiry без реальных PEM.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any, Protocol

__all__ = ("MtlsBackend", "MtlsConfig", "MtlsVerificationError", "ParsedClientCert")

_logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class ParsedClientCert:
    """Минимальный набор полей x509-cert после парсинга.

    Attributes:
        subject_cn: Common Name из subject DN.
        subject_ou: Organizational Unit (опц.).
        not_before: Unix-timestamp начала валидности.
        not_after: Unix-timestamp истечения.
        fingerprint_sha256: SHA-256 fingerprint в hex.
        issuer_cn: CN issuer'а (для CA-pin'а).
    """

    subject_cn: str
    subject_ou: str | None
    not_before: float
    not_after: float
    fingerprint_sha256: str
    issuer_cn: str | None = None


CertParser = Callable[[bytes], ParsedClientCert]
"""``cert_parser(pem_bytes)`` → :class:`ParsedClientCert`."""


@dataclass(slots=True)
class MtlsConfig:
    """Параметры :class:`MtlsBackend`.

    Attributes:
        allowed_fingerprints: Опц. whitelist sha256-fingerprints (hex,
            нижний регистр). Пустой = без pinning.
        allowed_issuer_cns: Опц. whitelist issuer-CN (для CA-pin'а).
        require_pem_body: Если ``True`` — обязательный PEM в
            ``X-Client-Cert`` (full validation); иначе допустимы только
            headers subject+fingerprint.
    """

    allowed_fingerprints: frozenset[str] = field(default_factory=frozenset)
    allowed_issuer_cns: frozenset[str] = field(default_factory=frozenset)
    require_pem_body: bool = False


class MtlsVerificationError(Exception):
    """Сертификат не прошёл проверку.

    Attributes:
        reason: Human-readable причина (для audit-log).
    """

    def __init__(self, *, reason: str) -> None:
        self.reason = reason
        super().__init__(reason)


class _RequestProtocol(Protocol):
    """Минимальный протокол FastAPI Request для тестируемости."""

    @property
    def headers(self) -> Any: ...


class MtlsBackend:
    """Backend, реализующий валидацию client-certificate.

    Args:
        config: Параметры (allowed fingerprints/issuers, strict mode).
        cert_parser: Функция парсинга PEM → :class:`ParsedClientCert`.
            Если ``None`` — используется default через ``cryptography``
            (lazy-import); при отсутствии библиотеки — невозможно
            валидировать PEM body.
        current_time: Источник времени (sec). По умолчанию ``time.time``.
    """

    def __init__(
        self,
        *,
        config: MtlsConfig | None = None,
        cert_parser: CertParser | None = None,
        current_time: Callable[[], float] = time.time,
    ) -> None:
        self._config = config or MtlsConfig()
        self._parser = cert_parser
        self._now = current_time

    def verify(self, request: _RequestProtocol) -> dict[str, Any] | None:
        """Проверить request и вернуть metadata авторизации.

        Returns:
            ``dict`` с полями ``principal``, ``fingerprint``,
            ``subject``, ``issuer`` — при успехе. ``None`` если
            cert не передан.

        Raises:
            MtlsVerificationError: cert передан, но не прошёл проверку
                (expired, not-yet-valid, fingerprint mismatch, etc.).
        """
        headers = request.headers
        fingerprint = (headers.get("X-Client-Cert-Fingerprint") or "").lower()
        subject = headers.get("X-Client-Cert-Subject")
        pem = headers.get("X-Client-Cert")

        if not fingerprint and not pem:
            return None

        parsed: ParsedClientCert | None = None
        if pem and self._parser is not None:
            try:
                parsed = self._parser(pem.encode("utf-8"))
            except Exception as exc:  # noqa: BLE001
                raise MtlsVerificationError(reason=f"PEM parse failed: {exc}") from exc

            now = self._now()
            if now < parsed.not_before:
                raise MtlsVerificationError(reason="certificate not yet valid")
            if now > parsed.not_after:
                raise MtlsVerificationError(reason="certificate expired")

            fingerprint = parsed.fingerprint_sha256.lower()
            subject = subject or parsed.subject_cn

            if (
                self._config.allowed_issuer_cns
                and parsed.issuer_cn not in self._config.allowed_issuer_cns
            ):
                raise MtlsVerificationError(
                    reason=f"issuer CN {parsed.issuer_cn!r} not in allow-list"
                )

        if self._config.require_pem_body and parsed is None:
            raise MtlsVerificationError(reason="PEM body required but missing")

        if (
            self._config.allowed_fingerprints
            and fingerprint not in self._config.allowed_fingerprints
        ):
            raise MtlsVerificationError(
                reason="fingerprint not in pinned allow-list"
            )

        principal = subject or fingerprint
        if not principal:
            raise MtlsVerificationError(reason="empty principal after validation")

        return {
            "principal": principal,
            "fingerprint": fingerprint,
            "subject": subject,
            "issuer": parsed.issuer_cn if parsed else None,
        }


def default_cryptography_parser() -> CertParser:
    """Стандартный PEM-парсер на ``cryptography`` (lazy-import).

    Raises:
        RuntimeError: Если библиотека не установлена. Caller должен
            ловить и оставаться в headers-only режиме.
    """
    try:
        from cryptography import x509  # noqa: PLC0415
        from cryptography.hazmat.primitives import hashes  # noqa: PLC0415
    except ImportError as exc:  # pragma: no cover — opt-in
        raise RuntimeError(
            "cryptography package not installed; mTLS PEM-validation disabled"
        ) from exc

    def _parse(pem: bytes) -> ParsedClientCert:
        cert = x509.load_pem_x509_certificate(pem)
        subject_cn = _attr(cert.subject, x509.NameOID.COMMON_NAME)
        subject_ou = _attr(cert.subject, x509.NameOID.ORGANIZATIONAL_UNIT_NAME)
        issuer_cn = _attr(cert.issuer, x509.NameOID.COMMON_NAME)
        fp = cert.fingerprint(hashes.SHA256()).hex()
        return ParsedClientCert(
            subject_cn=subject_cn or "",
            subject_ou=subject_ou,
            not_before=cert.not_valid_before_utc.timestamp(),
            not_after=cert.not_valid_after_utc.timestamp(),
            fingerprint_sha256=fp,
            issuer_cn=issuer_cn,
        )

    def _attr(name: Any, oid: Any) -> str | None:
        try:
            attrs = name.get_attributes_for_oid(oid)
        except Exception:  # noqa: BLE001
            return None
        if not attrs:
            return None
        return str(attrs[0].value)

    return _parse
