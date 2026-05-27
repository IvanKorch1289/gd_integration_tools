"""Cross-settings валидатор production-safety инвариантов (Sprint 16 Wave 3, CP-24).

Каждый ``Settings``-subclass валидирует свои поля независимо через
pydantic ``field_validator``/``model_validator``. Эти проверки срабатывают
в момент создания экземпляра Settings и ловят локальные ошибки (тип,
диапазон, формат). Однако **cross-settings инварианты** — отношения
между разными ``Settings``-объектами (например, «в production не должно
быть ``WAF.strict=False``») — pydantic выразить не может.

:class:`ConfigValidator` собирает все такие правила в одном месте и
вызывается из lifespan startup-хука как **fail-fast** gate: при
обнаружении :attr:`ConfigSeverity.CRITICAL` нарушений в
production-окружении приложение не стартует.

Закрывает блокеры
~~~~~~~~~~~~~~~~~

* **B-2** — WAF policy default permissive (``strict=False``).
* **B-9** — отсутствие cross-settings startup gate.

Defense-in-depth с pydantic-валидацией
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Некоторые правила (``app.debug_mode_in_prod``, ``security.jwt_secret_too_short``)
формально дублируют pydantic-валидации (``check_debug_mode`` в
:class:`AppBaseSettings`, ``min_length=32`` для ``secret_key``). При штатном
конструировании Settings pydantic срабатывает раньше и до
:class:`ConfigValidator` исполнение не доходит. Однако ConfigValidator
вызывается также в lifespan-хуке как **second line of defense** для путей,
обходящих pydantic: ``model_construct(...)``, прямые мутации
``object.__setattr__``, yaml-overlays, профильные оверрайды и тестовые
stub'ы Settings (SimpleNamespace). Дублирование умышленное.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from dataclasses import field as dc_field
from enum import StrEnum
from typing import TYPE_CHECKING, Final

if TYPE_CHECKING:
    from src.backend.core.config.base import AppBaseSettings
    from src.backend.core.config.database import DatabaseConnectionSettings
    from src.backend.core.config.security import SecureSettings
    from src.backend.core.config.services.cache import RedisSettings
    from src.backend.core.config.settings import Settings
    from src.backend.core.config.vault import VaultSettings
    from src.backend.core.config.waf import WafSettings

__all__ = (
    "ConfigSeverity",
    "ConfigValidator",
    "ConfigViolation",
    "ProductionConfigError",
    "validate_startup_config",
)


PRODUCTION_ENV: Final[str] = "production"

# Минимальная длина JWT/secret-ключа для production (рекомендация OWASP A02).
# Совпадает с pydantic ``min_length=32`` для AppBaseSettings.secret_key —
# дублирование намеренное (defense-in-depth, см. docstring модуля).
JWT_SECRET_MIN_LENGTH: Final[int] = 32

# Зависимости feature-flag'ов: ключ — зависимый flag, значение — кортеж
# имён flag'ов, которые должны быть включены, чтобы зависимый имел смысл.
# Правило ``feature_flag.dependency_unmet`` итерируется по нему.
#
# Критерии добавления пары:
#   1. dependent == strict-mode flag (без базового _enabled-партнёра);
#   2. требование логически обосновано (security posture, correctness);
#   3. оба флага существуют в features.py.
#
# Текущие пары (S31 w1):
#   - ``waf_strict_zero_allowlist`` (если появится) → ``waf_outbound_via_facade``
#     WAF zero-allowlist имеет смысл только при маршрутизации через facade.
_FEATURE_FLAG_DEPENDENCIES: Final[Mapping[str, tuple[str, ...]]] = {
    # supply_chain_strict_mode без supply_chain_finale_strict — WARNING (не блокирует startup)
    "supply_chain_strict_mode": ("supply_chain_finale_strict",),
}

# Пары зависимостей, которые блокируют production startup (CRITICAL).
# Критерии CRITICAL:
#   1. Security posture напрямую зависит от базового flag (без него — открытая дыра).
#   2. Влияние на audit/compliance/safety.
_FEATURE_FLAG_DEPENDENCIES_CRITICAL: Final[Mapping[str, tuple[str, ...]]] = {
    # WAF zero-allowlist (при появлении) — CRITICAL security posture violation
    # "waf_strict_zero_allowlist": ("waf_outbound_via_facade",),  # раскомментировать когда флаг появится
    # outbound_metering_strict без per-host baseline = неверные rate-лимиты
    "outbound_metering_strict": ("metering_per_host",),
}


class ConfigSeverity(StrEnum):
    """Уровень критичности нарушения конфигурации."""

    CRITICAL = "critical"
    WARNING = "warning"
    INFO = "info"


@dataclass(frozen=True, slots=True)
class ConfigViolation:
    """Описание одного обнаруженного нарушения конфигурации.

    Атрибуты:
        severity: Уровень критичности (CRITICAL блокирует prod-стартап).
        code: Стабильный машиночитаемый код (для DoD грепа и алертов).
        message: Человекочитаемое описание нарушения на русском.
        field: Точка конфигурации, к которой относится нарушение
            (``"<settings>.<attribute>"``).
        recommendation: Рекомендуемое действие для оператора.
        context: Дополнительный контекст (текущее значение и т.п.).
    """

    severity: ConfigSeverity
    code: str
    message: str
    field: str
    recommendation: str
    context: dict[str, object] = dc_field(default_factory=dict)


class ProductionConfigError(RuntimeError):
    """Поднимается, когда конфигурация production-окружения содержит
    хотя бы одно :attr:`ConfigSeverity.CRITICAL` нарушение.

    lifespan-хук перехватывает эту ошибку и преобразует её в
    fail-fast завершение startup-а.
    """

    def __init__(self, violations: tuple[ConfigViolation, ...]) -> None:
        self.violations = violations
        super().__init__(
            "Конфигурация production-окружения содержит критические нарушения: "
            + "; ".join(f"[{v.code}] {v.message}" for v in violations)
        )


class ConfigValidator:
    """Cross-settings валидатор production-safety инвариантов.

    Использование::

        from src.backend.core.config.settings import settings
        from src.backend.core.config.waf import waf_settings
        from src.backend.core.config.validator import ConfigValidator

        violations = ConfigValidator().validate(settings, waf_settings)
        for v in violations:
            ...

    Каждое правило сформулировано как отдельный приватный метод
    ``_check_<rule>``; добавление нового правила не требует изменения
    публичного API.
    """

    def validate(
        self, settings: "Settings", waf_settings: "WafSettings"
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

    @staticmethod
    def _is_prod(app: "AppBaseSettings") -> bool:
        """Признак production-окружения — единственная точка решения."""
        return app.environment == PRODUCTION_ENV

    def _check_waf_strict_prod(
        self, app: "AppBaseSettings", waf: "WafSettings"
    ) -> list[ConfigViolation]:
        """B-2: в production обязателен ``WAF_STRICT=true``."""
        if not self._is_prod(app):
            return []
        if waf.strict:
            return []
        return [
            ConfigViolation(
                severity=ConfigSeverity.CRITICAL,
                code="waf.strict_required_in_prod",
                message=(
                    "WAF policy permissive (strict=false) в production-окружении: "
                    "пустой allow_hosts трактуется как allow-all, любые внешние "
                    "запросы проходят без фильтрации."
                ),
                field="waf.strict",
                recommendation=(
                    "Установить WAF_STRICT=true и явный WAF_ALLOW_HOSTS=<список>."
                ),
                context={"strict": waf.strict, "environment": app.environment},
            )
        ]

    def _check_waf_strict_allow_empty(
        self, app: "AppBaseSettings", waf: "WafSettings"
    ) -> list[ConfigViolation]:
        """В production ``strict=True`` без allow_hosts блокирует ВСЕ исходящие.

        Это, как правило, ошибка конфигурации, а не намерение.
        """
        if not self._is_prod(app):
            return []
        if not waf.strict or waf.allow_hosts:
            return []
        return [
            ConfigViolation(
                severity=ConfigSeverity.CRITICAL,
                code="waf.allow_hosts_required_when_strict",
                message=(
                    "WAF strict=true и пустой allow_hosts в production: deny-all "
                    "для всех :external запросов — приложение не сможет обращаться "
                    "к внешним сервисам."
                ),
                field="waf.allow_hosts",
                recommendation=(
                    "Заполнить WAF_ALLOW_HOSTS списком хостов "
                    "(host1.example.com,host2.example.com,...)."
                ),
                context={"strict": waf.strict, "allow_hosts": list(waf.allow_hosts)},
            )
        ]

    def _check_clamav_fail_open_in_prod(
        self, app: "AppBaseSettings", waf: "WafSettings"
    ) -> list[ConfigViolation]:
        """Sprint 16 Wave 7 (B-3 finale): ClamAV enabled+fail_open в prod = WARNING.

        В production-strict при недоступности clamd безопаснее блокировать
        запрос (``fail_open=False``), чем пропускать без сканирования.
        Это рекомендация, не критическое нарушение (fail-open остаётся
        валидным выбором при ограниченной availability clamd).
        """
        if not self._is_prod(app):
            return []
        # Поле может отсутствовать в старых WafSettings — getattr с default.
        if not getattr(waf, "clamav_enabled", False):
            return []
        if not getattr(waf, "clamav_fail_open", True):
            return []
        return [
            ConfigViolation(
                severity=ConfigSeverity.WARNING,
                code="waf.clamav_fail_open_in_prod",
                message=(
                    "ClamAV scanner включён в production с fail_open=true: "
                    "при недоступности clamd запросы пройдут без сканирования. "
                    "В strict-prod рекомендуется fail_open=false."
                ),
                field="waf.clamav_fail_open",
                recommendation="WAF_CLAMAV_FAIL_OPEN=false для production-strict.",
                context={
                    "clamav_enabled": True,
                    "clamav_fail_open": True,
                },
            )
        ]

    def _check_swagger_in_prod(self, app: "AppBaseSettings") -> list[ConfigViolation]:
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

    def _check_redoc_in_prod(self, app: "AppBaseSettings") -> list[ConfigViolation]:
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
        self, app: "AppBaseSettings", secure: "SecureSettings"
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

    def _check_vault_disabled_in_prod(
        self, app: "AppBaseSettings", vault: "VaultSettings"
    ) -> list[ConfigViolation]:
        """В production отключение Vault приводит к чтению секретов из env."""
        if not self._is_prod(app):
            return []
        if vault.enabled:
            return []
        return [
            ConfigViolation(
                severity=ConfigSeverity.WARNING,
                code="vault.disabled_in_prod",
                message=(
                    "Vault отключён в production: секреты будут читаться из "
                    "переменных окружения без централизованной ротации и аудита."
                ),
                field="vault.enabled",
                recommendation=(
                    "VAULT_ENABLED=true и настроить VAULT_ADDR/VAULT_TOKEN."
                ),
                context={"vault_enabled": vault.enabled},
            )
        ]

    def _check_cors_credentials_with_wildcard(
        self, secure: "SecureSettings"
    ) -> list[ConfigViolation]:
        """CORS ``allow_credentials=true`` с wildcard origin запрещён по RFC.

        Браузеры (Chromium/Firefox/Safari) игнорируют ``Access-Control-
        Allow-Credentials: true`` если ``Access-Control-Allow-Origin: *``,
        и попытка такой комбинации обычно говорит о незавершённой
        конфигурации.
        """
        if not secure.cors_allow_credentials:
            return []
        if "*" not in secure.cors_origins:
            return []
        return [
            ConfigViolation(
                severity=ConfigSeverity.CRITICAL,
                code="security.cors_wildcard_with_credentials",
                message=(
                    "CORS allow_credentials=true вместе с wildcard origin '*' — "
                    "браузеры игнорируют комбинацию (CORS spec), фактически "
                    "credentials отправляются только same-origin."
                ),
                field="secure.cors_origins",
                recommendation=(
                    "Заменить '*' на явный список origin'ов или выключить "
                    "cors_allow_credentials."
                ),
                context={
                    "cors_origins": list(secure.cors_origins),
                    "cors_allow_credentials": secure.cors_allow_credentials,
                },
            )
        ]


    def _check_debug_mode_in_prod(
        self, app: "AppBaseSettings"
    ) -> list[ConfigViolation]:
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
                context={
                    "debug_mode": True,
                    "environment": app.environment,
                },
            )
        ]

    def _check_jwt_secret_too_short(
        self, app: "AppBaseSettings", secure: "SecureSettings"
    ) -> list[ConfigViolation]:
        """D14: ``secret_key`` короче ``JWT_SECRET_MIN_LENGTH`` символов.

        Defense-in-depth backstop для pydantic ``min_length=32`` в
        ``AppBaseSettings.secret_key`` и/или ``SecureSettings.jwt_secret``.
        Срабатывает на stub'ах Settings, обходящих pydantic, и на
        runtime-мутациях. Проверяет ``secret_key`` обоих контейнеров.
        """
        offenders: list[tuple[str, str]] = []
        for owner_name, owner in (("app", app), ("secure", secure)):
            for attr in ("secret_key", "jwt_secret", "jwt_secret_key"):
                raw = getattr(owner, attr, None)
                if raw is None:
                    continue
                value = (
                    raw.get_secret_value() if hasattr(raw, "get_secret_value") else raw
                )
                if not isinstance(value, str):
                    continue
                if len(value) < JWT_SECRET_MIN_LENGTH:
                    offenders.append((f"{owner_name}.{attr}", value))
        if not offenders:
            return []
        field, value = offenders[0]
        return [
            ConfigViolation(
                severity=ConfigSeverity.CRITICAL,
                code="security.jwt_secret_too_short",
                message=(
                    f"JWT/secret-ключ {field} длиной {len(value)} < "
                    f"{JWT_SECRET_MIN_LENGTH} символов: подвержен brute-force "
                    "и rainbow-table атакам."
                ),
                field=field,
                recommendation=(
                    f"Сгенерировать секрет ≥{JWT_SECRET_MIN_LENGTH} символов "
                    "через secrets.token_urlsafe(32) и ротировать через Vault."
                ),
                context={
                    "length": len(value),
                    "minimum": JWT_SECRET_MIN_LENGTH,
                    "fields_offended": [name for name, _ in offenders],
                },
            )
        ]

    def _check_database_host_in_prod(
        self, app: "AppBaseSettings", database: "DatabaseConnectionSettings"
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
        self, app: "AppBaseSettings", redis: "RedisSettings"
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
        self, app: "AppBaseSettings", redis: "RedisSettings"
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
        self, settings: "Settings"
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
                    context={
                        "dependent": dependent,
                        "unmet_requirements": list(unmet),
                    },
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
                    context={
                        "dependent": dependent,
                        "unmet_requirements": list(unmet),
                    },
                )
            )
        return violations


def validate_startup_config(
    settings: "Settings",
    waf_settings: "WafSettings",
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
