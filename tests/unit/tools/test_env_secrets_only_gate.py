"""TDD: ADR-0373 — правило «в .env.example только секреты» и связанные гейты.

Кластер CF3. Проверяем:

1. Канонический модуль правил (``tools/config_secret_rules.py``) — единый
   источник правды для обоих гейтов (``check_env_example`` и ``config_audit``).
2. ``tools/check_env_example.py``:
   * ClassVar/computed_field не попадают в сбор env-переменных;
   * документированный ключ обязан быть секретом;
   * значение секрета в шаблоне обязано быть пустым.
3. ``tools/config_audit.py``: scope ``missing`` блокирует missing-secret.
4. Реальный ``.env.example`` репозитория соответствует правилу.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from typer.testing import CliRunner

from tools import check_env_example as cee
from tools import config_audit
from tools.config_secret_rules import is_secret_field, is_secret_name

ROOT = Path(__file__).resolve().parents[3]

# Секреты, которые обязаны быть документированы в ``.env.example``
# (config_audit: missing-secret по 4 профилям).
REQUIRED_SECRET_VARS = (
    "AI_API_KEY",
    "AI_PASSWORD",
    "AI_USERNAME",
    "HTTP_CLIENT_CERT_PASSWORD",
    "INFLUXDB_TOKEN",
    "JUPYTER_HUB_API_TOKEN",
    "LANGFUSE_SECRET_KEY",
    "LDAP_BIND_PASSWORD",
    "LINEAGE_AUTH_TOKEN",
    "MINIMAX_API_KEY",
    "MINIMAX_PASSWORD",
    "MINIMAX_USERNAME",
    "MQTT_PASSWORD",
    "MQTT_USERNAME",
    "REDIS_SENTINEL_PASSWORD",
    "YANDEXGPT_API_KEY",
)

# Несекретные ключи, которые не должны попадать в ``.env.example``
# (значения живут в ``config_profiles/{profile}.yml``).
NON_SECRET_VARS = (
    "APP_PROFILE",
    "APP_ENV",
    "ENVIRONMENT",
    "CONSUL_ENABLED",
    "CONSUL_ADDR",
    "VAULT_MOUNT",
    "VAULT_NAMESPACE",
    "CDC_ENABLED",
    "JUPYTER_BACKEND",
    "DSL_YAML_STORE_DIR",
    "SEARXNG_BASE_URL",
    "SEARXNG_ENGINES",
    "FEATURE_PROD_HOT_RELOAD_DISABLE",
    "SEC_ROUTES_WITHOUT_API_KEY",
    "ALLOW_INSECURE_AUDIT_KEY",
)

# Мёртвые ключи (нет соответствующего Settings-поля).
DEAD_VARS = (
    "GIGACHAT_API_KEY",
    "TAVILY_API_KEY",
    "LOG_PASSWORD_SECRET",
    "LOG_ROOT_PASSWORD_SHA2",
)


class TestCanonicalSecretRules:
    """Канонические правила распознавания секретов."""

    @pytest.mark.parametrize(
        "name",
        [
            "password",
            "api_key",
            "secret_key",
            "token",
            "username",
            "credentials",
            "role_id",
            "secret_id",
            "webhook_url",
        ],
    )
    def test_secret_names_detected(self, name: str) -> None:
        """Канонический список помечает credential-имена как секреты."""
        assert is_secret_name(name) is True

    @pytest.mark.parametrize(
        "name",
        ["host", "port", "url", "retries", "timeout", "secret_path", "api_key_roles"],
    )
    def test_non_secret_names_skipped(self, name: str) -> None:
        """Несекретные имена не помечаются как секреты."""
        assert is_secret_name(name) is False

    def test_secret_str_annotation_wins(self) -> None:
        """Аннотация ``SecretStr`` — достаточный признак секрета."""
        assert is_secret_field("whatever", "SecretStr | None") is True

    def test_non_secret_type_hints_exclude(self) -> None:
        """Списки/флаги/числа секретами не являются даже по имени."""
        assert is_secret_field("api_key_admin_roles", "list[str]") is False
        assert is_secret_field("sanitize_api_keys", "bool") is False


class TestBothGatesShareRules:
    """Оба гейта используют один и тот же список правил."""

    def test_username_is_secret_in_check_env_example(self) -> None:
        """``check_env_example`` считает ``username`` секретом (как config_audit)."""
        assert cee._is_secret_field_name("username") is True

    def test_username_is_secret_in_config_audit(self) -> None:
        """``config_audit`` считает ``username`` секретом."""
        spec = config_audit.FieldSpec(
            name="username", annotation="str", has_default=True, is_computed=False
        )
        assert spec.is_secret is True

    def test_config_audit_uses_canonical_module(self) -> None:
        """Эвристика ``config_audit`` делегирована каноническому модулю."""
        assert config_audit.is_secret_field is is_secret_field


class TestCollectEnvVars:
    """Сбор env-переменных из Settings-моделей."""

    def test_classvar_fields_are_not_collected(self) -> None:
        """``yaml_group: ClassVar[str]`` — не env-переменная."""
        expected = cee.collect_expected_env_vars()
        pseudo = sorted(name for name in expected if name.endswith("_YAML_GROUP"))
        assert pseudo == [], f"ClassVar-поля попали в сбор: {pseudo}"

    def test_computed_fields_are_not_collected(self) -> None:
        """``@computed_field`` — не env-переменная."""
        expected = cee.collect_expected_env_vars()
        assert "MAIL_SMTP_URL" not in expected

    def test_expected_still_large(self) -> None:
        """После исключения ClassVar остаётся осмысленное число переменных."""
        assert len(cee.collect_expected_env_vars()) > 500


class TestSecretsOnlyCheck:
    """Проверка «документированный ключ = секрет и значение пустое»."""

    def test_non_secret_key_is_violation(self, tmp_path: Path) -> None:
        """Несекретный ключ в ``.env.example`` — нарушение."""
        env = tmp_path / ".env.example"
        env.write_text("APP_PROFILE=dev\n", encoding="utf-8")

        violations = cee.check_secrets_only(env, cee.CONFIG_DIR)

        assert [v.name for v in violations] == ["APP_PROFILE"]
        assert violations[0].reason == "non-secret"

    def test_non_empty_secret_value_is_violation(self, tmp_path: Path) -> None:
        """Непустое значение секрета (даже плейсхолдер) — нарушение."""
        env = tmp_path / ".env.example"
        env.write_text(
            "CONTEXT7_API_KEY=ctx7sk-REPLACE-WITH-YOUR-KEY\n", encoding="utf-8"
        )

        violations = cee.check_secrets_only(env, cee.CONFIG_DIR)

        assert [v.name for v in violations] == ["CONTEXT7_API_KEY"]
        assert violations[0].reason == "non-empty-secret"

    def test_empty_secret_value_is_allowed(self, tmp_path: Path) -> None:
        """Секрет с пустым значением — корректное документирование."""
        env = tmp_path / ".env.example"
        env.write_text("SEC_SECRET_KEY=\nDB_PASSWORD=\n", encoding="utf-8")

        assert cee.check_secrets_only(env, cee.CONFIG_DIR) == []

    def test_cli_secrets_only_fails_on_violation(self, tmp_path: Path) -> None:
        """CLI-режим ``--secrets-only`` возвращает exit 1 при нарушении."""
        env = tmp_path / ".env.example"
        env.write_text("APP_PROFILE=dev\n", encoding="utf-8")

        rc = cee.main(["--secrets-only", "--env-example", str(env)])

        assert rc == 1

    def test_cli_secrets_only_passes_on_clean_file(self, tmp_path: Path) -> None:
        """CLI-режим ``--secrets-only`` возвращает exit 0 на чистом файле."""
        env = tmp_path / ".env.example"
        env.write_text("SEC_SECRET_KEY=\n", encoding="utf-8")

        rc = cee.main(["--secrets-only", "--env-example", str(env)])

        assert rc == 0

    def test_json_output_contains_violations(self, tmp_path: Path) -> None:
        """JSON-вывод содержит список нарушений правила."""
        env = tmp_path / ".env.example"
        env.write_text("APP_PROFILE=dev\n", encoding="utf-8")

        result = CliRunner().invoke(
            cee.app, ["--secrets-only", "--json", "--env-example", str(env)]
        )

        payload = json.loads(result.stdout)
        assert payload["secrets_only_violations"], payload
        assert payload["secrets_only_violations"][0]["name"] == "APP_PROFILE"


class TestRealEnvExample:
    """Реальный ``.env.example`` репозитория соответствует правилу."""

    def test_no_violations(self) -> None:
        """В шаблоне остались только секреты с пустыми значениями."""
        violations = cee.check_secrets_only(cee.ENV_EXAMPLE, cee.CONFIG_DIR)
        assert violations == [], [v.detail for v in violations]

    def test_non_secret_keys_absent(self) -> None:
        """Несекретные ключи удалены из шаблона."""
        documented = dict(cee.parse_env_example(cee.ENV_EXAMPLE))
        for name in NON_SECRET_VARS:
            assert name not in documented, f"{name} не должен быть в .env.example"

    def test_dead_keys_absent(self) -> None:
        """Мёртвые ключи удалены из шаблона."""
        documented = dict(cee.parse_env_example(cee.ENV_EXAMPLE))
        for name in DEAD_VARS:
            assert name not in documented, f"{name} — мёртвый ключ"

    def test_all_values_empty(self) -> None:
        """Все значения в шаблоне пустые."""
        for name, value in cee.parse_env_example(cee.ENV_EXAMPLE):
            assert value.strip() == "", f"{name} содержит значение {value!r}"

    def test_required_secrets_documented(self) -> None:
        """Обязательные секреты документированы в шаблоне."""
        documented = dict(cee.parse_env_example(cee.ENV_EXAMPLE))
        for name in REQUIRED_SECRET_VARS:
            assert name in documented, f"{name} не документирован в .env.example"

    def test_rule_header_kept(self) -> None:
        """Шапка-правило «только секреты» сохранена."""
        header = cee.ENV_EXAMPLE.read_text(encoding="utf-8")[:2000]
        assert "ТОЛЬКО" in header


_SETTINGS_SOURCE = '''
from typing import ClassVar

from pydantic_settings import BaseSettings, SettingsConfigDict


class DemoSettings(BaseSettings):
    """Demo-настройки для тестов аудита."""

    yaml_group: ClassVar[str | None] = "demo"
    model_config = SettingsConfigDict(env_prefix="DEMO_", extra="forbid")

    known_field: int = 1
'''

_SECRET_CLASS = '''

class SecretSettings(BaseSettings):
    """Секретные demo-настройки."""

    yaml_group: ClassVar[str | None] = "secret_demo"
    model_config = SettingsConfigDict(env_prefix="SECRET_", extra="forbid")

    api_key: str
'''


@pytest.fixture
def demo_repo(tmp_path: Path) -> Path:
    """Мини-репозиторий: каталог моделей + каталог профилей."""
    (tmp_path / "config").mkdir()
    (tmp_path / "profiles").mkdir()
    (tmp_path / ".env.example").write_text("", encoding="utf-8")
    return tmp_path


def _run(repo: Path, *extra: str) -> int:
    """Запускает config_audit на demo-репозитории."""
    return config_audit.main(
        [
            "--config-dir",
            str(repo / "config"),
            "--profiles-dir",
            str(repo / "profiles"),
            "--env-example",
            str(repo / ".env.example"),
            "--allowlist",
            str(repo / "allowlist.txt"),
            *extra,
        ]
    )


class TestConfigAuditMissingScope:
    """Scope ``missing`` блокирует missing-secret."""

    def test_scope_missing_blocks_missing_secret(self, demo_repo: Path) -> None:
        """Незадокументированный секрет → exit 1 в scope ``missing``."""
        (demo_repo / "config" / "demo_settings.py").write_text(
            _SETTINGS_SOURCE + _SECRET_CLASS, encoding="utf-8"
        )
        (demo_repo / "profiles" / "dev.yml").write_text(
            "secret_demo:\n  api_key: x\n", encoding="utf-8"
        )

        assert _run(demo_repo, "--profile", "dev", "--scope", "missing") == 1

    def test_scope_missing_passes_when_documented(self, demo_repo: Path) -> None:
        """Задокументированный секрет → exit 0 в scope ``missing``."""
        (demo_repo / "config" / "demo_settings.py").write_text(
            _SETTINGS_SOURCE + _SECRET_CLASS, encoding="utf-8"
        )
        (demo_repo / "profiles" / "dev.yml").write_text(
            "secret_demo:\n  api_key: x\n", encoding="utf-8"
        )
        (demo_repo / ".env.example").write_text("SECRET_API_KEY=\n", encoding="utf-8")

        assert _run(demo_repo, "--profile", "dev", "--scope", "missing") == 0

    def test_scope_orphans_still_ignores_missing_secret(self, demo_repo: Path) -> None:
        """Scope ``orphans`` (по умолчанию) не блокируется на missing-secret."""
        (demo_repo / "config" / "demo_settings.py").write_text(
            _SETTINGS_SOURCE + _SECRET_CLASS, encoding="utf-8"
        )
        (demo_repo / "profiles" / "dev.yml").write_text(
            "secret_demo:\n  api_key: x\n", encoding="utf-8"
        )

        assert _run(demo_repo, "--profile", "dev") == 0

    def test_real_allowlist_has_no_missing_secret(self) -> None:
        """Baseline обновлён: missing-secret-долга не осталось."""
        allowlist = (ROOT / "tools" / "config_audit_allowlist.txt").read_text(
            encoding="utf-8"
        )
        entries = [
            line.strip()
            for line in allowlist.splitlines()
            if line.strip() and not line.strip().startswith("#")
        ]
        assert entries == [], entries

    def test_real_repo_has_no_new_missing_secret(self) -> None:
        """Гейт на реальном репозитории: scope ``missing`` — зелёный."""
        assert config_audit.main(["--scope", "missing"]) == 0
