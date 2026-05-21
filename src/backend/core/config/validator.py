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

Не пересекается с pydantic-валидацией
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

Дублирующие pydantic-проверки (``min_length=32`` для ``secret_key``,
``check_debug_mode`` в :class:`AppBaseSettings`) умышленно не
включены — они срабатывают раньше, на момент конструирования
Settings, и до :class:`ConfigValidator` исполнение просто не доходит.
"""

from __future__ import annotations

from dataclasses import dataclass
from dataclasses import field as dc_field
from enum import StrEnum
from typing import TYPE_CHECKING, Final

if TYPE_CHECKING:
    from src.backend.core.config.base import AppBaseSettings
    from src.backend.core.config.security import SecureSettings
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
        self,
        settings: "Settings",
        waf_settings: "WafSettings",
    ) -> tuple[ConfigViolation, ...]:
        """Возвращает кортеж обнаруженных нарушений (может быть пустым)."""
        violations: list[ConfigViolation] = []
        app = settings.app
        secure = settings.secure
        vault = settings.vault

        violations.extend(self._check_waf_strict_prod(app, waf_settings))
        violations.extend(self._check_waf_strict_allow_empty(app, waf_settings))
        violations.extend(self._check_swagger_in_prod(app))
        violations.extend(self._check_redoc_in_prod(app))
        violations.extend(self._check_admin_without_ips(app, secure))
        violations.extend(self._check_vault_disabled_in_prod(app, vault))
        violations.extend(self._check_cors_credentials_with_wildcard(secure))

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

    def _check_swagger_in_prod(
        self, app: "AppBaseSettings"
    ) -> list[ConfigViolation]:
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

    def _check_redoc_in_prod(
        self, app: "AppBaseSettings"
    ) -> list[ConfigViolation]:
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
                0 if v.severity == ConfigSeverity.CRITICAL
                else 1 if v.severity == ConfigSeverity.WARNING
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
