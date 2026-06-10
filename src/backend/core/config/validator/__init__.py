"""ConfigValidator package (S52 W2 decomp from validator.py 760 LOC).

14 _check_* methods decomposed в 3 mixin files:
- ``security_checks.py`` (6): WAF / ClamAV / Vault / CORS / JWT
- ``api_docs_checks.py`` (3): Swagger / ReDoc / admin endpoints
- ``infrastructure_checks.py`` (5): debug / DB / Redis / feature flags

Public surface (``validate``, ``_is_prod``, ``validate_startup_config``)
остается в ``__init__.py``.

Backward-compat: ``from src.backend.core.config.validator import ConfigValidator`` works.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.backend.core.config.settings import Settings
    from src.backend.core.config.waf import WafSettings

from src.backend.core.config.validator._helpers import (  # S52 W2: shared definitions
    PRODUCTION_ENV,
    ConfigSeverity,
    ConfigViolation,
    ProductionConfigError,
)
from src.backend.core.config.validator.api_docs_checks import (
    APIDocsChecksMixin,  # S52 W2: MRO
)
from src.backend.core.config.validator.infrastructure_checks import (
    InfrastructureChecksMixin,  # S52 W2: MRO
)
from src.backend.core.config.validator.security_checks import (
    SecurityChecksMixin,  # S52 W2: MRO
)

__all__ = (
    "APIDocsChecksMixin",
    "ConfigSeverity",
    "ConfigValidator",
    "ConfigViolation",
    "InfrastructureChecksMixin",
    "PRODUCTION_ENV",
    "ProductionConfigError",
    "SecurityChecksMixin",
    "validate_startup_config",
)


class ConfigValidator(
    SecurityChecksMixin,
    APIDocsChecksMixin,
    InfrastructureChecksMixin,
):
    """Production config validation (3 mixins = 14 _check_* methods + validate/_is_prod)."""

    __slots__ = ()

    def validate(
        self, settings: "Settings", waf_settings: "WafSettings",
    ) -> tuple[ConfigViolation, ...]:
        """Возвращает кортеж обнаруженных нарушений (может быть пустым).

        FeatureFlags для правила ``feature_flag.dependency_unmet`` берутся
        из ``settings.features``, а при отсутствии атрибута — лениво из
        глобального singleton ``core.config.features.feature_flags``.
        """
        violations: list[ConfigViolation] = []
        app = settings.app
        secure = settings.secure
        vault = settings.vault
        database = getattr(settings, "database", None)
        redis = getattr(settings, "redis", None)

        violations.extend(self._check_waf_strict_prod(app, waf_settings))
        violations.extend(self._check_waf_strict_allow_empty(app, waf_settings))
        violations.extend(self._check_clamav_fail_open_in_prod(app, waf_settings))
        violations.extend(self._check_swagger_in_prod(app))
        violations.extend(self._check_redoc_in_prod(app))
        violations.extend(self._check_admin_without_ips(app, secure))
        violations.extend(self._check_vault_disabled_in_prod(app, vault))
        violations.extend(self._check_cors_credentials_with_wildcard(secure))
        violations.extend(self._check_debug_mode_in_prod(app))
        violations.extend(self._check_jwt_secret_too_short(app, secure))
        if database is not None:
            violations.extend(self._check_database_host_in_prod(app, database))
        if redis is not None:
            violations.extend(self._check_redis_host_required_in_prod(app, redis))
            violations.extend(self._check_redis_host_localhost_in_prod(app, redis))
        violations.extend(self._check_feature_flag_dependency_unmet(settings))

        return tuple(violations)

    def _is_prod(self, app) -> bool:  # type: ignore[no-untyped-def]
        """Признак production-окружения — единственная точка решения."""
        return app.environment == PRODUCTION_ENV  # type: ignore[attr-defined]


# validate_startup_config (module-level, kept in __init__.py)
def validate_startup_config(
    settings: Settings,
    waf_settings: WafSettings,
    *,
    raise_on_critical_in_prod: bool = True,
) -> tuple[ConfigViolation, ...]:
    """Запускает :class:`ConfigValidator` и реализует fail-fast политику.

    Поведение:

    * Возвращает кортеж всех найденных нарушений (информативный отчёт).
    * Если ``raise_on_critical_in_prod=True``, в production-окружении
      и при наличии хотя бы одного :attr:`ConfigSeverity.CRITICAL` —
      поднимает :class:`ProductionConfigError`.
    * В non-production окружениях нарушения только возвращаются (lifespan
      залогирует их как WARNING без блокировки старта).

    Аргументы:
        settings: Корневой :class:`Settings`-объект.
        waf_settings: Глобальный :class:`WafSettings` (он не входит
            в корневой :class:`Settings`, поэтому передаётся отдельно).
        raise_on_critical_in_prod: Если ``False`` — поведение строго
            информативное (для тестов и dev-tools).

    Возвращает:
        Кортеж :class:`ConfigViolation`, отсортированный по severity
        (CRITICAL → WARNING → INFO).
    """
    violations = ConfigValidator().validate(settings, waf_settings)
    if not violations:
        return violations

    sorted_violations = tuple(
        sorted(
            violations,
            key=lambda v: (
                0
                if v.severity == ConfigSeverity.CRITICAL
                else 1
                if v.severity == ConfigSeverity.WARNING
                else 2
            ),
        )
    )

    if raise_on_critical_in_prod and settings.app.environment == PRODUCTION_ENV:
        critical = tuple(
            v for v in sorted_violations if v.severity == ConfigSeverity.CRITICAL
        )
        if critical:
            raise ProductionConfigError(critical)

    return sorted_violations

