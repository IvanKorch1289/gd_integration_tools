from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.backend.core.config.base import AppBaseSettings
    from src.backend.core.config.security import SecureSettings

from src.backend.core.config.validator._helpers import (  # S52 W2: shared definitions
    ConfigSeverity,
    ConfigViolation,
)


class APIDocsChecksMixin:
    """API/docs exposure checks (Swagger, ReDoc, admin endpoints) для ConfigValidator. S52 W2 extraction."""

    __slots__ = ()

    _is_prod: "Callable[[object], bool]"  # S52 W2: set on ConfigValidator (MRO root)
    # --- api_docs_checks methods ---

    def _check_swagger_in_prod(self, app: AppBaseSettings) -> list[ConfigViolation]:
        """Swagger UI в production раскрывает структуру API наружу."""
        if not self._is_prod(app):
            return []
        if not app.enable_swagger:
            return []
        return [
            ConfigViolation(
                severity=ConfigSeverity.WARNING,
                code="app.swagger_enabled_in_prod",
                message=(
                    "Swagger UI включён в production: интерфейс /docs раскрывает "
                    "полную структуру API и схем — снижает security posture."
                ),
                field="app.enable_swagger",
                recommendation="APP_ENABLE_SWAGGER=false для production.",
                context={"environment": app.environment},
            )
        ]

    def _check_redoc_in_prod(self, app: AppBaseSettings) -> list[ConfigViolation]:
        """ReDoc UI в production раскрывает структуру API наружу."""
        if not self._is_prod(app):
            return []
        if not app.enable_redoc:
            return []
        return [
            ConfigViolation(
                severity=ConfigSeverity.WARNING,
                code="app.redoc_enabled_in_prod",
                message=(
                    "ReDoc UI включён в production: интерфейс /redoc раскрывает "
                    "полную структуру API наружу."
                ),
                field="app.enable_redoc",
                recommendation="APP_ENABLE_REDOC=false для production.",
                context={"environment": app.environment},
            )
        ]

    def _check_admin_without_ips(
        self, app: AppBaseSettings, secure: SecureSettings
    ) -> list[ConfigViolation]:
        """Admin-эндпоинты в production обязаны быть защищены IP-allowlist."""
        if not self._is_prod(app):
            return []
        if not app.admin_enabled:
            return []
        if secure.admin_ips:
            return []
        return [
            ConfigViolation(
                severity=ConfigSeverity.CRITICAL,
                code="security.admin_ips_required_in_prod",
                message=(
                    "admin_enabled=true в production без admin_ips: "
                    "/admin/* эндпоинты доступны с любого источника."
                ),
                field="secure.admin_ips",
                recommendation=(
                    "Указать список доверенных IP в SEC_ADMIN_IPS "
                    "или выключить APP_ADMIN_ENABLED."
                ),
                context={
                    "admin_enabled": app.admin_enabled,
                    "admin_ips_count": len(secure.admin_ips),
                },
            )
        ]
