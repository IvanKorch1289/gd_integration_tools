"""Plugin manifest signature verification (Sprint 6 — audit 2026-09-22 P1).

Аудит finding #6: plugin loader развит, но нет подписанного манифеста,
capability declaration и provenance enforcement. Неподписанный или
запрашивающий лишние permissions plugin не загружается.

Этот модуль реализует:
1. ``SignedManifest`` — manifest + signature.
2. ``verify_signature`` — проверка подписи через cosign / SSH key.
3. ``CapabilityGate`` — enforce declared capabilities vs requested.

Production deployment требует:
- ``cosign`` CLI для keyless verification.
- Vault-stored ключ для key-based verification.

Sprint 6: structure + capability gate. Cosign integration — stub.
"""

from __future__ import annotations

import hashlib
import logging
import subprocess
from collections.abc import Callable
from dataclasses import dataclass, field
from enum import Enum

logger = logging.getLogger(__name__)


class VerificationResult(str, Enum):
    """Verification outcome."""

    VALID = "valid"
    INVALID_SIGNATURE = "invalid_signature"
    MISSING_SIGNATURE = "missing_signature"
    INVALID_CAPABILITIES = "invalid_capabilities"
    KEY_MISSING = "key_missing"
    COSIGN_UNAVAILABLE = "cosign_unavailable"


@dataclass(slots=True)
class PluginCapabilities:
    """Capability declaration для plugin.

    Должен match точно с runtime requested capabilities.
    """

    # Required: какие capabilities plugin запрашивает.
    required: tuple[str, ...]
    # Optional: какие capabilities plugin может использовать но не требует.
    optional: tuple[str, ...] = ()

    def is_subset_of(self, declared: PluginCapabilities) -> bool:
        """True если requested ⊆ declared."""
        return set(self.required).issubset(set(declared.required))


@dataclass(slots=True)
class SignedManifest:
    """Plugin manifest с signature.

    Attributes:
        manifest_hash: SHA-256 от manifest.toml content.
        signature: cosign signature blob (base64).
        public_key: public key (cosign.pub) или URL.
        capabilities: declared capabilities.
        plugin_name: имя plugin.
        plugin_version: semver version.
    """

    plugin_name: str
    plugin_version: str
    manifest_hash: str  # SHA-256 hex
    signature: str  # base64
    public_key: str  # cosign.pub content или URL
    capabilities: PluginCapabilities
    signed_at: str = ""  # ISO 8601
    signed_by: str = ""  # signer identity (email, OIDC subject, etc.)

    @classmethod
    def from_manifest(
        cls,
        manifest_path: str,
        capabilities: PluginCapabilities,
        public_key: str,
        signature: str,
        plugin_name: str,
        plugin_version: str,
    ) -> SignedManifest:
        """Construct from manifest file + signature."""
        with open(manifest_path, "rb") as f:
            content = f.read()
        manifest_hash = hashlib.sha256(content).hexdigest()
        return cls(
            plugin_name=plugin_name,
            plugin_version=plugin_version,
            manifest_hash=manifest_hash,
            signature=signature,
            public_key=public_key,
            capabilities=capabilities,
        )


@dataclass(slots=True)
class VerificationReport:
    """Result of verification."""

    result: VerificationResult
    message: str = ""
    details: dict[str, str] = field(default_factory=dict)


def verify_cosign_signature(
    manifest_path: str, signature: str, public_key: str
) -> VerificationReport:
    """Verify signature через cosign CLI.

    Args:
        manifest_path: path to manifest.toml file.
        signature: base64 signature blob.
        public_key: path to cosign.pub file или URL.

    Returns:
        VerificationReport с result=VALID или error reason.
    """
    try:
        # S603/S607: cosign CLI — фиксированный executable.
        result = subprocess.run(  # noqa: S603
            [  # noqa: S607
                "cosign",
                "verify-blob",
                "--signature",
                signature,
                "--key",
                public_key,
                manifest_path,
            ],
            capture_output=True,
            text=True,
            timeout=10,
        )
        if result.returncode == 0:
            return VerificationReport(result=VerificationResult.VALID)
        return VerificationReport(
            result=VerificationResult.INVALID_SIGNATURE, message=result.stderr[:200]
        )
    except FileNotFoundError:
        return VerificationReport(
            result=VerificationResult.COSIGN_UNAVAILABLE,
            message="cosign CLI not installed",
        )
    except subprocess.TimeoutExpired:
        return VerificationReport(
            result=VerificationResult.COSIGN_UNAVAILABLE,
            message="cosign verify timeout",
        )


def verify_capabilities(
    requested: PluginCapabilities, declared: PluginCapabilities
) -> VerificationReport:
    """Verify requested capabilities ⊆ declared capabilities.

    Args:
        requested: какие capabilities plugin запрашивает в runtime.
        declared: какие capabilities plugin объявил в signed manifest.

    Returns:
        VerificationReport. INVALID_CAPABILITIES если requested > declared.
    """
    if requested.is_subset_of(declared):
        return VerificationReport(result=VerificationResult.VALID)
    extra = set(requested.required) - set(declared.required)
    return VerificationReport(
        result=VerificationResult.INVALID_CAPABILITIES,
        message=f"Plugin requests undeclared capabilities: {sorted(extra)}",
        details={"undeclared": ",".join(sorted(extra))},
    )


class CapabilityGate:
    """Enforce plugin capabilities against signed manifest.

    Использование в plugin loader::

        gate = CapabilityGate(
            public_key_path="path/to/cosign.pub",
            verify_func=verify_cosign_signature,
        )

        # При загрузке plugin:
        report = gate.check(
            manifest_path="extensions/sk/plugin.toml",
            requested_capabilities=PluginCapabilities(required=("ai.invoke",)),
        )
        if report.result != VerificationResult.VALID:
            raise PluginSecurityError(report.message)
    """

    def __init__(
        self,
        public_key: str,
        verify_func: Callable[..., VerificationReport] | None = None,
    ) -> None:
        """Инициализация.

        Args:
            public_key: cosign.pub path/URL для verification.
            verify_func: custom verify function. None → verify_cosign_signature.
        """
        self._public_key = public_key
        self._verify = verify_func or verify_cosign_signature

    def check(
        self,
        manifest_path: str,
        signature: str,
        requested_capabilities: PluginCapabilities,
        declared_capabilities: PluginCapabilities,
    ) -> VerificationReport:
        """Verify signature + capabilities для plugin.

        Args:
            manifest_path: path к plugin.toml.
            signature: cosign signature blob.
            requested_capabilities: какие capabilities plugin хочет использовать.
            declared_capabilities: какие capabilities plugin объявил в signed manifest.

        Returns:
            VerificationReport с consolidated verdict.
        """
        # 1. Signature.
        sig_report = self._verify(
            manifest_path=manifest_path,
            signature=signature,
            public_key=self._public_key,
        )
        if sig_report.result != VerificationResult.VALID:
            return sig_report

        # 2. Capabilities.
        cap_report = verify_capabilities(
            requested=requested_capabilities, declared=declared_capabilities
        )
        if cap_report.result != VerificationResult.VALID:
            return cap_report

        return VerificationReport(result=VerificationResult.VALID)


__all__ = (
    "CapabilityGate",
    "PluginCapabilities",
    "SignedManifest",
    "VerificationReport",
    "VerificationResult",
    "verify_capabilities",
    "verify_cosign_signature",
)
