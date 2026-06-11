from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.backend.core.config.base import AppBaseSettings
    from src.backend.core.config.database import DatabaseConnectionSettings
    from src.backend.core.config.services.cache import RedisSettings
    from src.backend.core.config.settings import Settings

from src.backend.core.config.validator._helpers import (  # S52 W2: shared definitions
    _FEATURE_FLAG_DEPENDENCIES,
    _FEATURE_FLAG_DEPENDENCIES_CRITICAL,
    ConfigSeverity,
    ConfigViolation,
)


class InfrastructureChecksMixin:
    """Infrastructure checks (debug mode, database, Redis, feature flags) для ConfigValidator. S52 W2 extraction."""

    __slots__ = ()

    _is_prod: "Callable[[object], bool]"  # S52 W2: set on ConfigValidator (MRO root)
    # --- infrastructure_checks methods ---

    def _check_debug_mode_in_prod(self, app: AppBaseSettings) -> list[ConfigViolation]:
        """D14: ``debug_mode=True`` в production-окружении.

        Defense-in-depth backstop: pydantic ``check_debug_mode`` ловит
        случай при штатном конструировании ``AppBaseSettings``. Это правило
        срабатывает, если ``debug_mode`` был выставлен после init
        (mutation, ``model_construct``, тестовые stub'ы).
        """
        if not self._is_prod(app):
            return []
        if not getattr(app, "debug_mode", False):
            return []
        return [
            ConfigViolation(
                severity=ConfigSeverity.CRITICAL,
                code="app.debug_mode_in_prod",
                message=(
                    "debug_mode=true в production-окружении: расширенное "
                    "логирование, traceback'и в HTTP-ответах и отключённые "
                    "production-проверки повышают attack surface."
                ),
                field="app.debug_mode",
                recommendation=(
                    "APP_DEBUG_MODE=false для production. Если pydantic-валидация "
                    "была обойдена через model_construct/мутацию — устранить "
                    "обходной путь."
                ),
                context={"debug_mode": True, "environment": app.environment},
            )
        ]

    def _check_database_host_in_prod(
        self, app: AppBaseSettings, database: DatabaseConnectionSettings
    ) -> list[ConfigViolation]:
        """R-CFG-1: ``database.host`` пустой в production для non-sqlite.

        sqlite допускается без host (использует ``path``). Все остальные
        бэкенды (PostgreSQL/Oracle/MSSQL/MySQL/DB2) обязаны иметь явно
        указанный host в production.
        """
        if not self._is_prod(app):
            return []
        db_type = str(getattr(database, "type", "")).lower()
        if "sqlite" in db_type:
            return []
        if database.host:
            return []
        return [
            ConfigViolation(
                severity=ConfigSeverity.CRITICAL,
                code="database.host_required_in_prod",
                message=(
                    "database.host пустой в production: подключение к "
                    f"СУБД '{db_type or 'unknown'}' без хоста невозможно."
                ),
                field="database.host",
                recommendation=(
                    "Указать DB_HOST=<host> (например, 'pg.example.com'). "
                    "Для sqlite — переключить DB_TYPE=sqlite."
                ),
                context={
                    "db_type": db_type,
                    "host": database.host,
                    "environment": app.environment,
                },
            )
        ]

    def _check_redis_host_required_in_prod(
        self, app: AppBaseSettings, redis: RedisSettings
    ) -> list[ConfigViolation]:
        """R-CFG-2a: ``redis.host`` пустой в production при Redis enabled.

        Redis в production обязан иметь явно заданный хост — иначе
        распределённый кеш/rate-limit/idempotency недоступны.
        """
        if not self._is_prod(app):
            return []
        if not getattr(redis, "enabled", True):
            return []
        host = (redis.host or "").strip()
        if host:
            return []
        return [
            ConfigViolation(
                severity=ConfigSeverity.CRITICAL,
                code="redis.host_required_in_prod",
                message=(
                    "redis.host пустой в production при redis.enabled=true: "
                    "распределённый кеш недоступен."
                ),
                field="redis.host",
                recommendation=(
                    "Указать REDIS_HOST=<shared-instance> "
                    "или выключить REDIS_ENABLED=false."
                ),
                context={"environment": app.environment, "enabled": True},
            )
        ]

    def _check_redis_host_localhost_in_prod(
        self, app: AppBaseSettings, redis: RedisSettings
    ) -> list[ConfigViolation]:
        """R-CFG-2b: ``redis.host`` = localhost/127.0.0.1 в production.

        Redis в production должен указывать на shared instance (не localhost),
        иначе под несколькими репликами каждый pod пишет в свой локальный
        Redis, разрушая распределённый кеш/rate-limit/idempotency.
        """
        if not self._is_prod(app):
            return []
        if not getattr(redis, "enabled", True):
            return []
        host = (redis.host or "").strip().lower()
        if not host:
            # Пустой host уже обработан в _check_redis_host_required_in_prod
            return []
        if host in {"localhost", "127.0.0.1", "::1", "0.0.0.0"}:
            return [
                ConfigViolation(
                    severity=ConfigSeverity.CRITICAL,
                    code="redis.host_localhost_in_prod",
                    message=(
                        f"redis.host='{redis.host}' в production: каждая реплика "
                        "указывает на собственный локальный Redis, распределённый "
                        "кеш/rate-limit/idempotency работают некорректно."
                    ),
                    field="redis.host",
                    recommendation=(
                        "Указать REDIS_HOST=<shared-instance> (например, "
                        "'redis.internal' или service-DNS k8s)."
                    ),
                    context={"environment": app.environment, "host": redis.host},
                )
            ]
        return []

    def _check_feature_flag_dependency_unmet(
        self, settings: Settings
    ) -> list[ConfigViolation]:
        """D14: зависимый feature-flag включён, а требуемый — нет.

        Источник flag'ов: ``settings.features`` (если задан в Settings) либо
        глобальный singleton ``feature_flags``. Зависимости перечислены в
        ``_FEATURE_FLAG_DEPENDENCIES`` (WARNING) и
        ``_FEATURE_FLAG_DEPENDENCIES_CRITICAL`` (CRITICAL, блокирует startup).

        Severity дифференцирована:
        - CRITICAL: security posture напрямую зависит от базового flag
          (supply-chain integrity, WAF allowlist, audit compliance).
        - WARNING: остальные зависимости (не блокируют startup).
        """
        if not _FEATURE_FLAG_DEPENDENCIES and not _FEATURE_FLAG_DEPENDENCIES_CRITICAL:
            return []
        flags = getattr(settings, "features", None)
        if flags is None:
            try:
                from src.backend.core.config.features import feature_flags as _flags
            except ImportError:
                return []
            flags = _flags
        violations: list[ConfigViolation] = []

        # CRITICAL-зависимости
        for dependent, requirements in _FEATURE_FLAG_DEPENDENCIES_CRITICAL.items():
            if not getattr(flags, dependent, False):
                continue
            unmet = tuple(req for req in requirements if not getattr(flags, req, False))
            if not unmet:
                continue
            violations.append(
                ConfigViolation(
                    severity=ConfigSeverity.CRITICAL,
                    code="feature_flag.dependency_unmet",
                    message=(
                        f"feature-flag '{dependent}' включён, но требует "
                        f"{', '.join(unmet)} = true (CRITICAL: security posture)."
                    ),
                    field=f"features.{dependent}",
                    recommendation=(
                        f"Включить зависимости {', '.join(unmet)} либо выключить "
                        f"'{dependent}'."
                    ),
                    context={"dependent": dependent, "unmet_requirements": list(unmet)},
                )
            )

        # WARNING-зависимости
        for dependent, requirements in _FEATURE_FLAG_DEPENDENCIES.items():
            if not getattr(flags, dependent, False):
                continue
            unmet = tuple(req for req in requirements if not getattr(flags, req, False))
            if not unmet:
                continue
            violations.append(
                ConfigViolation(
                    severity=ConfigSeverity.WARNING,
                    code="feature_flag.dependency_unmet",
                    message=(
                        f"feature-flag '{dependent}' включён, но требует "
                        f"{', '.join(unmet)} = true."
                    ),
                    field=f"features.{dependent}",
                    recommendation=(
                        f"Включить зависимости {', '.join(unmet)} либо выключить "
                        f"'{dependent}'."
                    ),
                    context={"dependent": dependent, "unmet_requirements": list(unmet)},
                )
            )
        return violations
