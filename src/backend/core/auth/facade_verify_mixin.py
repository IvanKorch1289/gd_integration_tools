"""AuthVerifyMixin — SAML/LDAP verify method mixin (S64 M2-#1 split).

Extracted из :mod:`facade` (S164 W2 615 LOC god-object → split per
single-responsibility):
- :class:`AuthTokenMixin` (S63, M2-#1 partial) — issue_token + revoke_token
- :class:`AuthVerifyMixin` (S64, this file) — verify_saml_assertion + verify_ldap_credentials
- :class:`AuthFacade` (facade.py) — composition root + private _verify_* + check_permission + get_tenant + properties

Both methods use only ``self.quotas`` (property) and ``logger`` (module-level).
No inter-method state dependencies. Safe для mixin extraction.

Re-exported из :mod:`facade` для backward-compat public API.
"""

from __future__ import annotations

from src.backend.core.auth.auth_result import AuthResult

__all__ = ("AuthVerifyMixin",)


class AuthVerifyMixin:
    """SAML/LDAP verify method mixin (M2-#1 split).

    Methods:
    - verify_saml_assertion: ACS-gated SAML SSO flow
    - verify_ldap_credentials: LDAP bind + group lookup

    Methods access self.quotas (property, defined в :class:`AuthFacade`).
    MRO via mixin chain:
    ``AuthFacade(AuthTokenMixin, AuthVerifyMixin)`` (token layer first, verify layer second).
    """

    __slots__ = ()

    async def verify_saml_assertion(
        self,
        assertion_b64: str,
        *,
        expected_audience: str | None = None,
        expected_issuer: str | None = None,
    ) -> AuthResult:
        """S31 Task 4: SAML assertion verification with config gate.

        SAML requires the canonical ACS flow (configured SamlBackend,
        InResponseTo tracking, signature validator). For unit-tests and
        development, we provide a fail-closed path that ONLY succeeds when
        ``auth.saml.dev_mode`` feature flag is enabled.

        Args:
            assertion_b64: Base64-encoded SAML assertion.
            expected_audience: Expected ``AudienceRestriction`` (optional).
            expected_issuer: Expected ``Issuer`` (optional).

        Returns:
            :class:`AuthResult` with NameID if verified, else
            ``is_authenticated=False``.

        """
        from src.backend.core.auth.facade import logger  # S64: lazy import для circular dep

        # SAML requires ACS flow; fail-closed unless dev_mode flag is on.
        dev_mode = False
        try:
            from src.backend.core.config.features import feature_flags

            dev_mode = bool(getattr(feature_flags, "saml_sp_initiated_enabled", False))
        except (ImportError, AttributeError, RuntimeError) as ff_exc:
            # cycle-9/D-AUDIT-981: narrow exceptions + observability.
            import logging

            logging.getLogger(__name__).debug(
                "auth_facade.saml_dev_mode_fallback", extra={"error": str(ff_exc)}
            )

        if not dev_mode:
            logger.debug("SAML: dev_mode disabled, fail-closed")
            return AuthResult(
                is_authenticated=False, metadata={"error": "saml_requires_acs_flow"}
            )

        if not assertion_b64:
            return AuthResult(
                is_authenticated=False, metadata={"error": "saml_empty_assertion"}
            )

        try:
            import base64

            # P0-S6 (audit 2026-08-19): B314 fix -- defusedxml для защиты
            # от XXE/billion-laughs DoS. ElementTree обрабатывает
            # entity-expansion атаки при парсинге untrusted XML.
            from defusedxml import ElementTree as ET

            xml_bytes = base64.b64decode(assertion_b64)
            root = ET.fromstring(xml_bytes)  # nosec B314 -- defusedxml safe
            ns = {"saml": "urn:oasis:names:tc:SAML:2.0:assertion"}
            name_id_el = root.find(".//saml:NameID", ns)
            subject_el = root.find(".//saml:Subject", ns)
            issuer_el = root.find(".//saml:Issuer", ns)
            audience_el = root.find(".//saml:AudienceRestriction/saml:Audience", ns)
            name_id = (name_id_el.text if name_id_el is not None else None) or (
                subject_el.text if subject_el is not None else None
            )
            issuer = issuer_el.text if issuer_el is not None else None
            audience = audience_el.text if audience_el is not None else None

            if expected_issuer and issuer != expected_issuer:
                return AuthResult(
                    is_authenticated=False, metadata={"error": "saml_issuer_mismatch"}
                )
            if expected_audience and audience != expected_audience:
                return AuthResult(
                    is_authenticated=False, metadata={"error": "saml_audience_mismatch"}
                )
            if not name_id:
                return AuthResult(
                    is_authenticated=False, metadata={"error": "saml_no_nameid"}
                )
            return AuthResult(
                is_authenticated=True,
                method="saml",
                subject=str(name_id),
                metadata={"issuer": issuer, "audience": audience, "dev_mode": True},
            )
        except Exception as exc:
            logger.debug("SAML dev-mode verify failed: %s", exc)
            return AuthResult(
                is_authenticated=False,
                metadata={"error": f"saml_dev_verify_failed: {exc}"},
            )

    async def verify_ldap_credentials(
        self, username: str, password: str, *, tenant_id: str | None = None
    ) -> AuthResult:
        """S31 Task 4: LDAP bind verification.

        Uses :class:`ldap_client_factory` (canonical core-owned
        :class:`AdDirectoryClientProtocol`) to bind the user. On success,
        returns ``AuthResult`` with subject=``username`` and optional
        tenant_id. On failure, returns ``is_authenticated=False``.

        Args:
            username: LDAP/AD user (sAMAccountName или UPN).
            password: Plain password (passed to LDAP bind).
            tenant_id: Optional tenant mapping (added to metadata).

        Returns:
            :class:`AuthResult` with ``is_authenticated`` status.

        """
        from src.backend.core.auth.facade import logger  # S64: lazy import для circular dep

        if not username or not password:
            return AuthResult(
                is_authenticated=False, metadata={"error": "ldap_empty_credentials"}
            )

        try:
            from src.backend.core.auth.ldap_client_factory import get_ad_client

            client = get_ad_client()
            success = await client.bind(username, password)
            if not success:
                return AuthResult(
                    is_authenticated=False, metadata={"error": "ldap_bind_failed"}
                )
            return AuthResult(
                is_authenticated=True,
                method="ldap",
                subject=str(username),
                tenant_id=tenant_id,
                metadata={"directory": "ldap", "tenant_id": tenant_id},
            )
        except Exception as exc:
            logger.warning("LDAP bind failed: %s", exc)
            return AuthResult(is_authenticated=False, metadata={"error": "ldap_failed"})