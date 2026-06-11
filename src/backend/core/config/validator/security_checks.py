from __future__ import annotations

from collections.abc import Callable
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from src.backend.core.config.base import AppBaseSettings
    from src.backend.core.config.security import SecureSettings
    from src.backend.core.config.vault import VaultSettings
    from src.backend.core.config.waf import WafSettings

from src.backend.core.config.validator._helpers import (  # S52 W2: shared definitions
    JWT_SECRET_MIN_LENGTH,
    ConfigSeverity,
    ConfigViolation,
)


class SecurityChecksMixin:
    """Security validation checks (WAF, ClamAV, Vault, CORS, JWT) для ConfigValidator. S52 W2 extraction."""

    __slots__ = ()

    _is_prod: "Callable[[object], bool]"  # S52 W2: set on ConfigValidator (MRO root)
    # --- security_checks methods ---

    def _check_waf_strict_prod(
        self, app: AppBaseSettings, waf: WafSettings
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
        self, app: AppBaseSettings, waf: WafSettings
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
        self, app: AppBaseSettings, waf: WafSettings
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
                context={"clamav_enabled": True, "clamav_fail_open": True},
            )
        ]

    def _check_vault_disabled_in_prod(
        self, app: AppBaseSettings, vault: VaultSettings
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
        self, secure: SecureSettings
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

    def _check_jwt_secret_too_short(
        self, app: AppBaseSettings, secure: SecureSettings
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
