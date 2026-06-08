"""Auth methods endpoint (S58 W6e).

``GET /auth/methods`` — endpoint который фронт вызывает для
rendering login form (выбор method: password / ldap).

Response::

    {
      "methods": ["password", "ldap"],
      "ldap_enabled": true,
      "password_enabled": true,
      "default_method": "ldap",
      "deprecations": {
        "password": "Password auth is deprecated; will be removed in S59+"
      }
    }

Source:
* ``feature_flags.saml_ad_login_enabled`` (sprint6 settings) — controls
  ``ldap_enabled`` (глобальный toggle per design S58 W6);
* ``password_enabled`` — всегда True (пока не удалим, per S58 W6
  "не убирай авторизацию по паролю" — kept for backward compat);
* ``default_method`` — ``"ldap"`` если LDAP available, иначе ``"password"``.

Front integration:
* Streamlit / BFF вызывает этот endpoint при init login form;
* Рендерит кнопки только для enabled methods;
* ``default_method`` используется для autofocus на primary action.

Не требует auth (вызывается до login).
"""
from __future__ import annotations

from fastapi import APIRouter
from pydantic import BaseModel, Field

from src.backend.infrastructure.logging.factory import get_logger

_logger = get_logger(__name__)

router = APIRouter(prefix="/auth", tags=["auth"])


class AuthMethodsResponse(BaseModel):
    """Response для GET /auth/methods (S58 W6e)."""

    methods: list[str] = Field(
        ...,
        description="Список enabled auth methods ('password', 'ldap').",
    )
    ldap_enabled: bool = Field(
        ...,
        description="True если ``feature_flags.saml_ad_login_enabled = True`` AND LDAP сконфигурирован.",
    )
    password_enabled: bool = Field(
        ...,
        description="True пока password auth НЕ удалён (всегда True per S58 W6 backward compat).",
    )
    default_method: str = Field(
        ...,
        description="Рекомендованный primary method для login form ('ldap' или 'password').",
    )
    deprecations: dict[str, str] = Field(
        default_factory=dict,
        description="Per-method deprecation messages (для badge/tooltip в UI).",
    )


@router.get(
    "/methods",
    response_model=AuthMethodsResponse,
    summary="Список enabled auth methods (для front login form)",
    description=(
        "Возвращает какие auth methods доступны + какой default. "
        "Front вызывает при init login screen."
    ),
)
async def get_auth_methods() -> AuthMethodsResponse:
    """Список enabled auth methods (S58 W6e).

    Читает:
    * ``feature_flags.saml_ad_login_enabled`` (Sprint 6);
    * ``ldap_settings.is_configured()`` (S58 W6a).

    Returns:
        AuthMethodsResponse с актуальным состоянием.
    """
    from src.backend.core.auth.ldap_client_factory import get_ad_client
    from src.backend.core.config.services.ldap import ldap_settings

    # LDAP enabled: feature flag ON AND client can be instantiated
    ldap_client = get_ad_client()
    ldap_enabled = ldap_client is not None and (
        ldap_client.is_available() if ldap_client else False
    )

    # Sanity: settings.is_configured() — flag may be on but env vars empty
    if ldap_enabled and not ldap_settings.is_configured():
        _logger.warning(
            "auth.methods: feature flag on but ldap_settings not configured"
        )
        ldap_enabled = False

    methods: list[str] = []
    if ldap_enabled:
        methods.append("ldap")
    # Password — всегда available per S58 W6 design (kept for backward compat)
    methods.append("password")

    # Default: ldap if enabled (preferred per S58 W6), else password
    default_method = "ldap" if ldap_enabled else "password"

    deprecations: dict[str, str] = {}
    if "password" in methods:
        deprecations["password"] = (
            "Password auth is deprecated; LDAP preferred. "
            "Will be removed when front fully migrates (S59+). "
            "See ADR-0085 (S58 W6)."
        )

    return AuthMethodsResponse(
        methods=methods,
        ldap_enabled=ldap_enabled,
        password_enabled=True,
        default_method=default_method,
        deprecations=deprecations,
    )
