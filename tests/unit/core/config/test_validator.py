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
    secret_key: str = "x" * 64,
) -> SimpleNamespace:
    """Фабрика SimpleNamespace, имитирующего AppBaseSettings."""
    return SimpleNamespace(
        environment=environment,
        debug_mode=debug_mode,
        enable_swagger=enable_swagger,
        enable_redoc=enable_redoc,
        admin_enabled=admin_enabled,
        secret_key=secret_key,
    )


def _make_secure(
    *,
    cors_origins: list[str] | None = None,
    cors_allow_credentials: bool = True,
    admin_ips: set[str] | None = None,
    secret_key: str = "y" * 64,
) -> SimpleNamespace:
    """Фабрика SimpleNamespace, имитирующего SecureSettings."""
    return SimpleNamespace(
        cors_origins=cors_origins or [],
        cors_allow_credentials=cors_allow_credentials,
        admin_ips=admin_ips or set(),
        secret_key=secret_key,
    )


def _make_vault(*, enabled: bool = True) -> SimpleNamespace:
    """Фабрика SimpleNamespace, имитирующего VaultSettings."""
    return SimpleNamespace(enabled=enabled)


def _make_settings(
    *,
    app: SimpleNamespace | None = None,
    secure: SimpleNamespace | None = None,
    vault: SimpleNamespace | None = None,
    database: SimpleNamespace | None = None,
    redis: SimpleNamespace | None = None,
) -> SimpleNamespace:
    """Корневой Settings-mock."""
    ns = SimpleNamespace(
        app=app or _make_app(),
        secure=secure or _make_secure(),
        vault=vault or _make_vault(),
    )
    if database is not None:
        ns.database = database
    if redis is not None:
        ns.redis = redis
    return ns


def _make_database(*, host: str = "db.example.com", db_type: str = "postgresql") -> SimpleNamespace:
    """Фабрика SimpleNamespace, имитирующего DatabaseConnectionSettings."""
    return SimpleNamespace(host=host, type=db_type)


def _make_redis(*, host: str = "redis.internal", enabled: bool = True) -> SimpleNamespace:
    """Фабрика SimpleNamespace, имитирующего RedisSettings."""
    return SimpleNamespace(host=host, enabled=enabled)


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


class TestDebugModeInProd:
    """D14: ``debug_mode=True`` в production — defense-in-depth backstop."""

    def test_debug_true_in_prod_is_critical(self) -> None:
        settings = _make_settings(
            app=_make_app(environment="production", debug_mode=True)
        )
        waf = _make_waf(strict=True, allow_hosts=("a",))
        violations = ConfigValidator().validate(settings, waf)
        v = next(v for v in violations if v.code == "app.debug_mode_in_prod")
        assert v.severity == ConfigSeverity.CRITICAL

    def test_debug_true_in_dev_is_clean(self) -> None:
        settings = _make_settings(
            app=_make_app(environment="development", debug_mode=True)
        )
        waf = _make_waf(strict=False)
        violations = ConfigValidator().validate(settings, waf)
        assert "app.debug_mode_in_prod" not in _codes(violations)


class TestJwtSecretTooShort:
    """D14: ``secret_key`` < 32 символов — defense-in-depth backstop."""

    def test_short_secret_is_critical_regardless_of_env(self) -> None:
        settings = _make_settings(
            app=_make_app(environment="development", secret_key="short"),
        )
        waf = _make_waf(strict=False)
        violations = ConfigValidator().validate(settings, waf)
        v = next(v for v in violations if v.code == "security.jwt_secret_too_short")
        assert v.severity == ConfigSeverity.CRITICAL
        assert v.context["length"] == 5
        assert v.context["minimum"] == 32

    def test_long_secret_is_clean(self) -> None:
        settings = _make_settings(
            app=_make_app(environment="production", secret_key="A" * 64),
            secure=_make_secure(secret_key="B" * 64),
        )
        waf = _make_waf(strict=True, allow_hosts=("a",))
        violations = ConfigValidator().validate(settings, waf)
        assert "security.jwt_secret_too_short" not in _codes(violations)


class TestFeatureFlagDependencyUnmet:
    """D14: зависимый feature-flag включён без требуемой зависимости."""

    def test_no_dependencies_returns_no_violation(self) -> None:
        """Пустой ``_FEATURE_FLAG_DEPENDENCIES`` → нет нарушений."""
        settings = _make_settings(app=_make_app(environment="production"))
        waf = _make_waf(strict=True, allow_hosts=("a",))
        violations = ConfigValidator().validate(settings, waf)
        assert "feature_flag.dependency_unmet" not in _codes(violations)

    def test_unmet_dependency_yields_warning(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """С временно добавленной зависимостью правило отрабатывает."""
        from src.backend.core.config import validator as validator_module

        monkeypatch.setattr(
            validator_module,
            "_FEATURE_FLAG_DEPENDENCIES",
            {"foo_strict": ("foo_enabled",)},
        )
        fake_flags = SimpleNamespace(foo_strict=True, foo_enabled=False)
        settings = _make_settings(app=_make_app(environment="production"))
        settings.features = fake_flags
        waf = _make_waf(strict=True, allow_hosts=("a",))
        violations = ConfigValidator().validate(settings, waf)
        v = next(v for v in violations if v.code == "feature_flag.dependency_unmet")
        assert v.severity == ConfigSeverity.WARNING
        assert v.context["dependent"] == "foo_strict"
        assert v.context["unmet_requirements"] == ["foo_enabled"]

    def test_unmet_critical_dependency_yields_critical(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Зависимость в _FEATURE_FLAG_DEPENDENCIES_CRITICAL → CRITICAL severity."""
        from src.backend.core.config import validator as validator_module

        monkeypatch.setattr(
            validator_module,
            "_FEATURE_FLAG_DEPENDENCIES_CRITICAL",
            {"bar_strict": ("bar_enabled",)},
        )
        fake_flags = SimpleNamespace(bar_strict=True, bar_enabled=False)
        settings = _make_settings(app=_make_app(environment="production"))
        settings.features = fake_flags
        waf = _make_waf(strict=True, allow_hosts=("a",))
        violations = ConfigValidator().validate(settings, waf)
        v = next(v for v in violations if v.code == "feature_flag.dependency_unmet")
        assert v.severity == ConfigSeverity.CRITICAL
        assert v.context["dependent"] == "bar_strict"
        assert v.context["unmet_requirements"] == ["bar_enabled"]


class TestDatabaseHostInProd:
    """R-CFG-1: ``database.host`` пустой в production для non-sqlite — CRITICAL."""

    def test_empty_host_postgres_in_prod_is_critical(self) -> None:
        settings = _make_settings(
            app=_make_app(environment="production"),
            database=_make_database(host="", db_type="postgresql"),
        )
        waf = _make_waf(strict=True, allow_hosts=("a",))
        violations = ConfigValidator().validate(settings, waf)
        v = next(v for v in violations if v.code == "database.host_required_in_prod")
        assert v.severity == ConfigSeverity.CRITICAL

    def test_empty_host_sqlite_in_prod_is_clean(self) -> None:
        settings = _make_settings(
            app=_make_app(environment="production"),
            database=_make_database(host="", db_type="sqlite"),
        )
        waf = _make_waf(strict=True, allow_hosts=("a",))
        violations = ConfigValidator().validate(settings, waf)
        assert "database.host_required_in_prod" not in _codes(violations)

    def test_host_set_in_prod_is_clean(self) -> None:
        settings = _make_settings(
            app=_make_app(environment="production"),
            database=_make_database(host="pg.example.com", db_type="postgresql"),
        )
        waf = _make_waf(strict=True, allow_hosts=("a",))
        violations = ConfigValidator().validate(settings, waf)
        assert "database.host_required_in_prod" not in _codes(violations)

    def test_empty_host_in_dev_is_clean(self) -> None:
        settings = _make_settings(
            app=_make_app(environment="development"),
            database=_make_database(host="", db_type="postgresql"),
        )
        waf = _make_waf(strict=False)
        violations = ConfigValidator().validate(settings, waf)
        assert "database.host_required_in_prod" not in _codes(violations)


class TestRedisHostInProd:
    """R-CFG-2: ``redis.host`` пустой/localhost в prod с enabled — CRITICAL."""

    def test_empty_host_enabled_in_prod_is_critical(self) -> None:
        settings = _make_settings(
            app=_make_app(environment="production"),
            redis=_make_redis(host="", enabled=True),
        )
        waf = _make_waf(strict=True, allow_hosts=("a",))
        violations = ConfigValidator().validate(settings, waf)
        v = next(v for v in violations if v.code == "redis.host_required_in_prod")
        assert v.severity == ConfigSeverity.CRITICAL

    def test_localhost_enabled_in_prod_is_critical(self) -> None:
        settings = _make_settings(
            app=_make_app(environment="production"),
            redis=_make_redis(host="localhost", enabled=True),
        )
        waf = _make_waf(strict=True, allow_hosts=("a",))
        violations = ConfigValidator().validate(settings, waf)
        v = next(v for v in violations if v.code == "redis.host_localhost_in_prod")
        assert v.severity == ConfigSeverity.CRITICAL

    def test_127_0_0_1_enabled_in_prod_is_critical(self) -> None:
        settings = _make_settings(
            app=_make_app(environment="production"),
            redis=_make_redis(host="127.0.0.1", enabled=True),
        )
        waf = _make_waf(strict=True, allow_hosts=("a",))
        violations = ConfigValidator().validate(settings, waf)
        assert "redis.host_localhost_in_prod" in _codes(violations)

    def test_shared_host_enabled_in_prod_is_clean(self) -> None:
        settings = _make_settings(
            app=_make_app(environment="production"),
            redis=_make_redis(host="redis.internal", enabled=True),
        )
        waf = _make_waf(strict=True, allow_hosts=("a",))
        violations = ConfigValidator().validate(settings, waf)
        assert "redis.host_required_in_prod" not in _codes(violations)
        assert "redis.host_localhost_in_prod" not in _codes(violations)

    def test_localhost_disabled_in_prod_is_clean(self) -> None:
        settings = _make_settings(
            app=_make_app(environment="production"),
            redis=_make_redis(host="localhost", enabled=False),
        )
        waf = _make_waf(strict=True, allow_hosts=("a",))
        violations = ConfigValidator().validate(settings, waf)
        assert "redis.host_localhost_in_prod" not in _codes(violations)

    def test_localhost_in_dev_is_clean(self) -> None:
        settings = _make_settings(
            app=_make_app(environment="development"),
            redis=_make_redis(host="localhost", enabled=True),
        )
        waf = _make_waf(strict=False)
        violations = ConfigValidator().validate(settings, waf)
        assert "redis.host_localhost_in_prod" not in _codes(violations)


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
