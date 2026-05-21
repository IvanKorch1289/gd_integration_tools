"""Тесты ConfigValidator (Sprint 16 Wave 3, CP-24, B-2, B-9).

Проверяет cross-settings правила:

* ``waf.strict_required_in_prod`` — B-2 закрытие;
* ``waf.allow_hosts_required_when_strict`` — strict без allow_hosts = deny-all;
* ``app.swagger_enabled_in_prod`` / ``app.redoc_enabled_in_prod`` — warning;
* ``security.admin_ips_required_in_prod`` — admin без allowlist в prod;
* ``vault.disabled_in_prod`` — warning;
* ``security.cors_wildcard_with_credentials`` — RFC violation независимо
  от окружения;
* fail-fast поведение :func:`validate_startup_config` в production.

Используем :class:`types.SimpleNamespace` вместо реальных pydantic
``Settings``-объектов, чтобы тест-фикстуры не зависели от полной
YAML/env-конфигурации проекта.
"""

# ruff: noqa: S101

from __future__ import annotations

from types import SimpleNamespace

import pytest

from src.backend.core.config.validator import (
    ConfigSeverity,
    ConfigValidator,
    ConfigViolation,
    ProductionConfigError,
    validate_startup_config,
)


def _make_app(
    *,
    environment: str = "development",
    debug_mode: bool = False,
    enable_swagger: bool = True,
    enable_redoc: bool = False,
    admin_enabled: bool = False,
) -> SimpleNamespace:
    """Фабрика SimpleNamespace, имитирующего AppBaseSettings."""
    return SimpleNamespace(
        environment=environment,
        debug_mode=debug_mode,
        enable_swagger=enable_swagger,
        enable_redoc=enable_redoc,
        admin_enabled=admin_enabled,
    )


def _make_secure(
    *,
    cors_origins: list[str] | None = None,
    cors_allow_credentials: bool = True,
    admin_ips: set[str] | None = None,
) -> SimpleNamespace:
    """Фабрика SimpleNamespace, имитирующего SecureSettings."""
    return SimpleNamespace(
        cors_origins=cors_origins or [],
        cors_allow_credentials=cors_allow_credentials,
        admin_ips=admin_ips or set(),
    )


def _make_vault(*, enabled: bool = True) -> SimpleNamespace:
    """Фабрика SimpleNamespace, имитирующего VaultSettings."""
    return SimpleNamespace(enabled=enabled)


def _make_settings(
    *,
    app: SimpleNamespace | None = None,
    secure: SimpleNamespace | None = None,
    vault: SimpleNamespace | None = None,
) -> SimpleNamespace:
    """Корневой Settings-mock."""
    return SimpleNamespace(
        app=app or _make_app(),
        secure=secure or _make_secure(),
        vault=vault or _make_vault(),
    )


def _make_waf(
    *,
    strict: bool = False,
    allow_hosts: tuple[str, ...] = (),
    clamav_enabled: bool = False,
    clamav_fail_open: bool = True,
) -> SimpleNamespace:
    """Фабрика SimpleNamespace, имитирующего WafSettings."""
    return SimpleNamespace(
        strict=strict,
        allow_hosts=allow_hosts,
        clamav_enabled=clamav_enabled,
        clamav_fail_open=clamav_fail_open,
    )


def _codes(violations: tuple[ConfigViolation, ...]) -> set[str]:
    """Собрать множество кодов нарушений для удобной проверки."""
    return {v.code for v in violations}


class TestWafStrictInProd:
    """B-2 — WAF strict в production-окружении."""

    def test_strict_false_in_prod_is_critical(self) -> None:
        settings = _make_settings(app=_make_app(environment="production"))
        waf = _make_waf(strict=False)
        violations = ConfigValidator().validate(settings, waf)
        codes = _codes(violations)
        assert "waf.strict_required_in_prod" in codes
        critical = [v for v in violations if v.severity == ConfigSeverity.CRITICAL]
        assert any(v.code == "waf.strict_required_in_prod" for v in critical)

    def test_strict_true_in_prod_with_allow_hosts_is_clean(self) -> None:
        settings = _make_settings(app=_make_app(environment="production"))
        waf = _make_waf(strict=True, allow_hosts=("api.example.com",))
        violations = ConfigValidator().validate(settings, waf)
        assert "waf.strict_required_in_prod" not in _codes(violations)
        assert "waf.allow_hosts_required_when_strict" not in _codes(violations)

    def test_strict_false_in_dev_is_ok(self) -> None:
        settings = _make_settings(app=_make_app(environment="development"))
        waf = _make_waf(strict=False)
        violations = ConfigValidator().validate(settings, waf)
        assert "waf.strict_required_in_prod" not in _codes(violations)

    def test_strict_true_in_prod_without_allow_hosts_is_critical(self) -> None:
        settings = _make_settings(app=_make_app(environment="production"))
        waf = _make_waf(strict=True, allow_hosts=())
        violations = ConfigValidator().validate(settings, waf)
        assert "waf.allow_hosts_required_when_strict" in _codes(violations)


class TestDocsUIInProd:
    """Swagger/ReDoc должны быть выключены в production."""

    def test_swagger_in_prod_is_warning(self) -> None:
        settings = _make_settings(
            app=_make_app(environment="production", enable_swagger=True)
        )
        waf = _make_waf(strict=True, allow_hosts=("a",))
        violations = ConfigValidator().validate(settings, waf)
        v = next(v for v in violations if v.code == "app.swagger_enabled_in_prod")
        assert v.severity == ConfigSeverity.WARNING

    def test_redoc_in_prod_is_warning(self) -> None:
        settings = _make_settings(
            app=_make_app(
                environment="production", enable_swagger=False, enable_redoc=True
            )
        )
        waf = _make_waf(strict=True, allow_hosts=("a",))
        violations = ConfigValidator().validate(settings, waf)
        v = next(v for v in violations if v.code == "app.redoc_enabled_in_prod")
        assert v.severity == ConfigSeverity.WARNING

    def test_swagger_in_dev_is_ok(self) -> None:
        settings = _make_settings(
            app=_make_app(environment="development", enable_swagger=True)
        )
        waf = _make_waf(strict=False)
        violations = ConfigValidator().validate(settings, waf)
        assert "app.swagger_enabled_in_prod" not in _codes(violations)


class TestAdminIPs:
    """В production admin-эндпоинты обязаны быть защищены IP-allowlist."""

    def test_admin_enabled_no_ips_in_prod_is_critical(self) -> None:
        settings = _make_settings(
            app=_make_app(environment="production", admin_enabled=True),
            secure=_make_secure(admin_ips=set()),
        )
        waf = _make_waf(strict=True, allow_hosts=("a",))
        violations = ConfigValidator().validate(settings, waf)
        v = next(
            v for v in violations if v.code == "security.admin_ips_required_in_prod"
        )
        assert v.severity == ConfigSeverity.CRITICAL

    def test_admin_enabled_with_ips_in_prod_is_clean(self) -> None:
        settings = _make_settings(
            app=_make_app(environment="production", admin_enabled=True),
            secure=_make_secure(admin_ips={"10.0.0.1"}),
        )
        waf = _make_waf(strict=True, allow_hosts=("a",))
        violations = ConfigValidator().validate(settings, waf)
        assert "security.admin_ips_required_in_prod" not in _codes(violations)

    def test_admin_disabled_no_ips_in_prod_is_clean(self) -> None:
        settings = _make_settings(
            app=_make_app(environment="production", admin_enabled=False),
            secure=_make_secure(admin_ips=set()),
        )
        waf = _make_waf(strict=True, allow_hosts=("a",))
        violations = ConfigValidator().validate(settings, waf)
        assert "security.admin_ips_required_in_prod" not in _codes(violations)


class TestVaultInProd:
    """Vault отключён в production = WARNING."""

    def test_vault_disabled_in_prod_is_warning(self) -> None:
        settings = _make_settings(
            app=_make_app(environment="production"),
            vault=_make_vault(enabled=False),
        )
        waf = _make_waf(strict=True, allow_hosts=("a",))
        violations = ConfigValidator().validate(settings, waf)
        v = next(v for v in violations if v.code == "vault.disabled_in_prod")
        assert v.severity == ConfigSeverity.WARNING

    def test_vault_enabled_in_prod_is_clean(self) -> None:
        settings = _make_settings(
            app=_make_app(environment="production"),
            vault=_make_vault(enabled=True),
        )
        waf = _make_waf(strict=True, allow_hosts=("a",))
        violations = ConfigValidator().validate(settings, waf)
        assert "vault.disabled_in_prod" not in _codes(violations)


class TestCorsCredentialsWildcard:
    """CORS wildcard + allow_credentials — RFC violation независимо от env."""

    def test_wildcard_with_credentials_is_critical_in_dev(self) -> None:
        settings = _make_settings(
            app=_make_app(environment="development"),
            secure=_make_secure(cors_origins=["*"], cors_allow_credentials=True),
        )
        waf = _make_waf(strict=False)
        violations = ConfigValidator().validate(settings, waf)
        v = next(
            v
            for v in violations
            if v.code == "security.cors_wildcard_with_credentials"
        )
        assert v.severity == ConfigSeverity.CRITICAL

    def test_wildcard_without_credentials_is_clean(self) -> None:
        settings = _make_settings(
            secure=_make_secure(cors_origins=["*"], cors_allow_credentials=False),
        )
        waf = _make_waf()
        violations = ConfigValidator().validate(settings, waf)
        assert "security.cors_wildcard_with_credentials" not in _codes(violations)

    def test_explicit_origins_with_credentials_is_clean(self) -> None:
        settings = _make_settings(
            secure=_make_secure(
                cors_origins=["https://app.example.com"], cors_allow_credentials=True
            ),
        )
        waf = _make_waf()
        violations = ConfigValidator().validate(settings, waf)
        assert "security.cors_wildcard_with_credentials" not in _codes(violations)


class TestClamAVFailOpenInProd:
    """Sprint 16 Wave 7 (B-3 finale): ClamAV fail_open в prod = WARNING."""

    def test_clamav_enabled_fail_open_in_prod_is_warning(self) -> None:
        settings = _make_settings(app=_make_app(environment="production"))
        waf = _make_waf(
            strict=True,
            allow_hosts=("a",),
            clamav_enabled=True,
            clamav_fail_open=True,
        )
        violations = ConfigValidator().validate(settings, waf)
        v = next(v for v in violations if v.code == "waf.clamav_fail_open_in_prod")
        assert v.severity == ConfigSeverity.WARNING

    def test_clamav_enabled_fail_closed_in_prod_is_clean(self) -> None:
        settings = _make_settings(app=_make_app(environment="production"))
        waf = _make_waf(
            strict=True,
            allow_hosts=("a",),
            clamav_enabled=True,
            clamav_fail_open=False,
        )
        violations = ConfigValidator().validate(settings, waf)
        assert "waf.clamav_fail_open_in_prod" not in _codes(violations)

    def test_clamav_disabled_no_warning(self) -> None:
        settings = _make_settings(app=_make_app(environment="production"))
        waf = _make_waf(
            strict=True, allow_hosts=("a",), clamav_enabled=False
        )
        violations = ConfigValidator().validate(settings, waf)
        assert "waf.clamav_fail_open_in_prod" not in _codes(violations)

    def test_clamav_fail_open_in_dev_no_warning(self) -> None:
        settings = _make_settings(app=_make_app(environment="development"))
        waf = _make_waf(clamav_enabled=True, clamav_fail_open=True)
        violations = ConfigValidator().validate(settings, waf)
        assert "waf.clamav_fail_open_in_prod" not in _codes(violations)


class TestCleanConfig:
    """Корректная prod-конфигурация не даёт ни одного нарушения."""

    def test_clean_prod_config_returns_empty(self) -> None:
        settings = _make_settings(
            app=_make_app(
                environment="production",
                enable_swagger=False,
                enable_redoc=False,
                admin_enabled=True,
            ),
            secure=_make_secure(
                cors_origins=["https://app.example.com"],
                cors_allow_credentials=True,
                admin_ips={"10.0.0.1"},
            ),
            vault=_make_vault(enabled=True),
        )
        waf = _make_waf(strict=True, allow_hosts=("api.example.com",))
        violations = ConfigValidator().validate(settings, waf)
        assert violations == ()


class TestValidateStartupConfig:
    """fail-fast обёртка validate_startup_config."""

    def test_critical_in_prod_raises_production_config_error(self) -> None:
        settings = _make_settings(app=_make_app(environment="production"))
        waf = _make_waf(strict=False)
        with pytest.raises(ProductionConfigError) as excinfo:
            validate_startup_config(settings, waf)
        assert any(
            v.code == "waf.strict_required_in_prod" for v in excinfo.value.violations
        )

    def test_warning_only_in_prod_does_not_raise(self) -> None:
        settings = _make_settings(
            app=_make_app(
                environment="production", enable_swagger=True, admin_enabled=False
            ),
            secure=_make_secure(admin_ips=set()),
            vault=_make_vault(enabled=True),
        )
        waf = _make_waf(strict=True, allow_hosts=("a",))
        # Только WARNING из swagger → не блокирует
        result = validate_startup_config(settings, waf)
        assert any(v.code == "app.swagger_enabled_in_prod" for v in result)
        assert all(v.severity != ConfigSeverity.CRITICAL for v in result)

    def test_critical_in_dev_does_not_raise(self) -> None:
        settings = _make_settings(
            app=_make_app(environment="development"),
            secure=_make_secure(cors_origins=["*"], cors_allow_credentials=True),
        )
        waf = _make_waf(strict=False)
        result = validate_startup_config(settings, waf)
        assert any(
            v.code == "security.cors_wildcard_with_credentials" for v in result
        )

    def test_raise_disabled_returns_violations(self) -> None:
        settings = _make_settings(app=_make_app(environment="production"))
        waf = _make_waf(strict=False)
        result = validate_startup_config(
            settings, waf, raise_on_critical_in_prod=False
        )
        assert any(v.code == "waf.strict_required_in_prod" for v in result)

    def test_sorted_by_severity(self) -> None:
        """CRITICAL идёт перед WARNING в результирующем кортеже."""
        settings = _make_settings(
            app=_make_app(
                environment="production",
                enable_swagger=True,
                admin_enabled=True,
            ),
            secure=_make_secure(admin_ips=set()),
            vault=_make_vault(enabled=False),
        )
        waf = _make_waf(strict=False)
        result = validate_startup_config(
            settings, waf, raise_on_critical_in_prod=False
        )
        severities = [v.severity for v in result]
        # Все CRITICAL должны идти раньше любого WARNING
        first_warning = next(
            (i for i, s in enumerate(severities) if s == ConfigSeverity.WARNING),
            None,
        )
        if first_warning is not None:
            assert all(
                s == ConfigSeverity.CRITICAL for s in severities[:first_warning]
            )

    def test_empty_violations_returns_empty_tuple(self) -> None:
        settings = _make_settings(
            app=_make_app(
                environment="production",
                enable_swagger=False,
                enable_redoc=False,
                admin_enabled=True,
            ),
            secure=_make_secure(
                cors_origins=["https://app.example.com"],
                cors_allow_credentials=True,
                admin_ips={"10.0.0.1"},
            ),
            vault=_make_vault(enabled=True),
        )
        waf = _make_waf(strict=True, allow_hosts=("api.example.com",))
        result = validate_startup_config(settings, waf)
        assert result == ()
