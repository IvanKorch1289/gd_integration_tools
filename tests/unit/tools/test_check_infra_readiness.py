"""Тесты гейта готовности инфраструктуры (``tools/check_infra_readiness.py``).

Покрытие 6 пунктов инфра-чек-листа (ADR-0441, ``docs/ops/infra-release-checklist.md``):
happy-путь (пункт закрыт → ``ok``) и fail-путь (небезопасное/несогласованное
значение → ``fail``), плюс exit-коды CLI (0/1/2), ``--strict`` и ``--json``.

Гейт работает по конфигурации: живая инфраструктура (Vault, JWKS-сервис,
ClickHouse) не опрашивается — отсутствие секрета в окружении это
предупреждение, а не падение.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tools.check_infra_readiness import (
    ENV_CLICKHOUSE_ENABLED,
    ENV_CLICKHOUSE_HOST,
    ENV_CLICKHOUSE_HTTP_PORT,
    ENV_DB_REPLICA_DSN,
    ENV_JUPYTER_HUB_API_TOKEN,
    ENV_JUPYTER_HUB_BASE_URL,
    ENV_JUPYTER_HUB_ENABLED,
    ENV_JWKS_URL,
    ENV_OPEN_WEBUI_API_KEY,
    ENV_OPEN_WEBUI_BASE_URL,
    ENV_SNAPSHOT_MODE,
    ENV_SNAPSHOT_SERVICE_DSN,
    INFRA_CHECKS,
    InfraFinding,
    Severity,
    check_clickhouse,
    check_db_replica_dsn,
    check_jupyter_hub,
    check_jwks,
    check_open_webui,
    check_snapshot_service_role,
    load_merged_profile,
    main,
    run_checks,
)

#: Все env-имена, которые читает гейт (для изоляции окружения тестов).
ALL_ENV_VARS = (
    "SEC_ALGORITHM",
    ENV_JWKS_URL,
    ENV_SNAPSHOT_MODE,
    ENV_SNAPSHOT_SERVICE_DSN,
    ENV_CLICKHOUSE_ENABLED,
    ENV_CLICKHOUSE_HOST,
    ENV_CLICKHOUSE_HTTP_PORT,
    ENV_OPEN_WEBUI_BASE_URL,
    ENV_OPEN_WEBUI_API_KEY,
    ENV_JUPYTER_HUB_ENABLED,
    ENV_JUPYTER_HUB_BASE_URL,
    ENV_JUPYTER_HUB_API_TOKEN,
    ENV_DB_REPLICA_DSN,
)

#: Готовый прод-профиль: все 6 пунктов закрыты.
READY_BASE_YAML = """
security:
  algorithm: "RS256"
snapshot:
  enabled: true
  mode: "service-role"
clickhouse:
  enabled: true
  host: "clickhouse.internal"
  http_port: 8123
open_webui:
  base_url: "http://open-webui:3000"
ai_providers:
  fallback_chain:
    - "perplexity"
    - "open_webui"
jupyter_hub:
  enabled: true
  base_url: "https://jupyter.internal"
database:
  replica_dsn: null
"""

READY_PROD_YAML = """
features:
  audit_clickhouse_enabled: true
"""

#: Окружение, дополняющее ``READY_BASE_YAML`` до полной готовности.
READY_ENV: dict[str, str] = {
    ENV_JWKS_URL: "https://idp.internal/.well-known/jwks.json",
    ENV_SNAPSHOT_SERVICE_DSN: "postgresql+asyncpg://svc:pwd@pg.internal:5432/appdb",
    ENV_OPEN_WEBUI_API_KEY: "vault-value",
    ENV_JUPYTER_HUB_API_TOKEN: "vault-token",
}


@pytest.fixture(autouse=True)
def _isolated_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Убирает из окружения переменные, которые читает гейт."""
    for name in ALL_ENV_VARS:
        monkeypatch.delenv(name, raising=False)


def _write_profiles(
    directory: Path, base_yaml: str = READY_BASE_YAML, prod_yaml: str = READY_PROD_YAML
) -> Path:
    """Создаёт каталог с ``base.yml`` + ``prod.yml`` и возвращает его путь."""
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "base.yml").write_text(base_yaml, encoding="utf-8")
    (directory / "prod.yml").write_text(prod_yaml, encoding="utf-8")
    return directory


def _severities(findings: list[InfraFinding]) -> list[Severity]:
    """Извлекает список severity из результатов проверки."""
    return [finding.severity for finding in findings]


class TestJwksCheck:
    """Пункт 1: keypair + JWKS-сервис (https)."""

    @pytest.mark.unit
    def test_rs256_with_https_jwks_is_ok(self) -> None:
        """RS256 + https-endpoint — пункт закрыт."""
        findings = check_jwks(
            {"security": {"algorithm": "RS256"}},
            {ENV_JWKS_URL: "https://idp.internal/jwks.json"},
        )
        assert _severities(findings) == [Severity.OK]

    @pytest.mark.unit
    def test_rs256_without_jwks_fails(self) -> None:
        """Асимметричный алгоритм без JWKS-endpoint — проверять подпись нечем."""
        findings = check_jwks({"security": {"algorithm": "RS256"}}, {})
        assert _severities(findings) == [Severity.FAIL]

    @pytest.mark.unit
    def test_http_jwks_url_fails(self) -> None:
        """http:// в JWKS-URL — небезопасное значение (SSRF-guard)."""
        findings = check_jwks(
            {"security": {"algorithm": "RS256"}},
            {ENV_JWKS_URL: "http://idp.internal/jwks.json"},
        )
        assert _severities(findings) == [Severity.FAIL]
        assert "https" in findings[0].message

    @pytest.mark.unit
    def test_hs256_without_jwks_is_warning(self) -> None:
        """Симметричный алгоритм без JWKS — предупреждение, не падение."""
        findings = check_jwks({"security": {"algorithm": "HS256"}}, {})
        assert _severities(findings) == [Severity.WARNING]

    @pytest.mark.unit
    def test_unknown_algorithm_fails(self) -> None:
        """Неизвестный алгоритм подписи — нарушение конфигурации."""
        findings = check_jwks({"security": {"algorithm": "HS999"}}, {})
        assert _severities(findings) == [Severity.FAIL]

    @pytest.mark.unit
    def test_env_overrides_profile(self) -> None:
        """Env приоритетнее YAML (ADR-0372)."""
        findings = check_jwks(
            {"security": {"algorithm": "HS256"}},
            {"SEC_ALGORITHM": "RS256", ENV_JWKS_URL: "https://idp.internal/j"},
        )
        assert _severities(findings) == [Severity.OK]


class TestSnapshotServiceRoleCheck:
    """Пункт 2: роль БД с BYPASSRLS + ``SNAPSHOT_SERVICE_DSN``."""

    @pytest.mark.unit
    def test_service_role_with_dsn_is_ok(self) -> None:
        """Режим service-role + корректный DSN — пункт закрыт."""
        findings = check_snapshot_service_role(
            {"snapshot": {"mode": "service-role"}},
            {ENV_SNAPSHOT_SERVICE_DSN: "postgresql+asyncpg://s:p@pg.internal:5432/db"},
        )
        assert _severities(findings) == [Severity.OK]

    @pytest.mark.unit
    def test_service_role_without_dsn_is_warning(self) -> None:
        """Нет DSN — предупреждение: секрет придёт из Vault."""
        findings = check_snapshot_service_role(
            {"snapshot": {"mode": "service-role"}}, {}
        )
        assert _severities(findings) == [Severity.WARNING]

    @pytest.mark.unit
    def test_service_role_with_broken_dsn_fails(self) -> None:
        """Некорректный DSN (не URL с хостом) — падение."""
        findings = check_snapshot_service_role(
            {"snapshot": {"mode": "service-role"}},
            {ENV_SNAPSHOT_SERVICE_DSN: "not-a-dsn"},
        )
        assert _severities(findings) == [Severity.FAIL]

    @pytest.mark.unit
    def test_single_tenant_without_dsn_is_ok(self) -> None:
        """Режим single-tenant служебной роли не требует."""
        findings = check_snapshot_service_role(
            {"snapshot": {"mode": "single-tenant"}}, {}
        )
        assert _severities(findings) == [Severity.OK]

    @pytest.mark.unit
    def test_dsn_with_other_mode_is_warning(self) -> None:
        """DSN задан, а режим другой — несогласованность (предупреждение)."""
        findings = check_snapshot_service_role(
            {"snapshot": {"mode": "per-tenant"}},
            {ENV_SNAPSHOT_SERVICE_DSN: "postgresql+asyncpg://s:p@pg.internal:5432/db"},
        )
        assert _severities(findings) == [Severity.WARNING]

    @pytest.mark.unit
    def test_unknown_mode_fails(self) -> None:
        """Неизвестный режим снапшота — падение."""
        findings = check_snapshot_service_role({"snapshot": {"mode": "bogus"}}, {})
        assert _severities(findings) == [Severity.FAIL]

    @pytest.mark.unit
    def test_mode_from_env(self) -> None:
        """Режим читается из env (SNAPSHOT_MODE)."""
        findings = check_snapshot_service_role(
            {"snapshot": {"mode": "single-tenant"}},
            {
                ENV_SNAPSHOT_MODE: "service-role",
                ENV_SNAPSHOT_SERVICE_DSN: "postgresql+asyncpg://s:p@pg.internal:5432/db",
            },
        )
        assert _severities(findings) == [Severity.OK]


class TestClickHouseCheck:
    """Пункт 3: ClickHouse в проде."""

    @pytest.mark.unit
    def test_enabled_with_external_host_is_ok(self) -> None:
        """ClickHouse включён и указывает на внешний хост — пункт закрыт."""
        findings = check_clickhouse(
            {
                "features": {"audit_clickhouse_enabled": True},
                "clickhouse": {
                    "enabled": True,
                    "host": "clickhouse.internal",
                    "http_port": 8123,
                },
            },
            {},
        )
        assert _severities(findings) == [Severity.OK]

    @pytest.mark.unit
    def test_audit_flag_on_but_clickhouse_off_fails(self) -> None:
        """Трейл audit-событий включён, а ClickHouse выключен — падение."""
        findings = check_clickhouse(
            {
                "features": {"audit_clickhouse_enabled": True},
                "clickhouse": {"enabled": False, "host": "localhost"},
            },
            {},
        )
        assert _severities(findings) == [Severity.FAIL]

    @pytest.mark.unit
    def test_loopback_host_fails(self) -> None:
        """В prod писать в localhost нельзя — падение."""
        findings = check_clickhouse(
            {
                "features": {"audit_clickhouse_enabled": True},
                "clickhouse": {"enabled": True, "host": "localhost", "http_port": 8123},
            },
            {},
        )
        assert _severities(findings) == [Severity.FAIL]

    @pytest.mark.unit
    def test_invalid_http_port_fails(self) -> None:
        """Некорректный HTTP-порт — падение."""
        findings = check_clickhouse(
            {
                "features": {"audit_clickhouse_enabled": True},
                "clickhouse": {"enabled": True, "host": "ch.internal", "http_port": 0},
            },
            {},
        )
        assert _severities(findings) == [Severity.FAIL]

    @pytest.mark.unit
    def test_not_used_is_ok(self) -> None:
        """ClickHouse не используется — действие владельца не требуется."""
        findings = check_clickhouse(
            {"features": {"audit_clickhouse_enabled": False}}, {}
        )
        assert _severities(findings) == [Severity.OK]

    @pytest.mark.unit
    def test_env_overrides_profile(self) -> None:
        """Env-параметры ClickHouse приоритетнее YAML."""
        findings = check_clickhouse(
            {
                "features": {"audit_clickhouse_enabled": True},
                "clickhouse": {
                    "enabled": False,
                    "host": "localhost",
                    "http_port": 8123,
                },
            },
            {
                ENV_CLICKHOUSE_ENABLED: "true",
                ENV_CLICKHOUSE_HOST: "clickhouse.internal",
                ENV_CLICKHOUSE_HTTP_PORT: "8124",
            },
        )
        assert _severities(findings) == [Severity.OK]


class TestOpenWebuiCheck:
    """Пункт 4: OpenWebUI + согласованность с ``fallback_chain``."""

    @pytest.mark.unit
    def test_in_chain_with_url_and_key_is_ok(self) -> None:
        """Провайдер в цепочке, endpoint и ключ заданы — пункт закрыт."""
        findings = check_open_webui(
            {
                "ai_providers": {"fallback_chain": ["perplexity", "open_webui"]},
                "open_webui": {"base_url": "http://open-webui:3000"},
            },
            {ENV_OPEN_WEBUI_API_KEY: "vault-value"},
        )
        assert _severities(findings) == [Severity.OK]

    @pytest.mark.unit
    def test_in_chain_without_base_url_fails(self) -> None:
        """Провайдер в цепочке без endpoint — откат ушёл бы в никуда."""
        findings = check_open_webui(
            {"ai_providers": {"fallback_chain": ["open_webui"]}, "open_webui": {}},
            {ENV_OPEN_WEBUI_API_KEY: "vault-value"},
        )
        assert _severities(findings) == [Severity.FAIL]

    @pytest.mark.unit
    def test_in_chain_with_loopback_url_fails(self) -> None:
        """Loopback-endpoint в prod (ADR-0407) — падение."""
        findings = check_open_webui(
            {
                "ai_providers": {"fallback_chain": ["open_webui"]},
                "open_webui": {"base_url": "http://127.0.0.1:3000"},
            },
            {ENV_OPEN_WEBUI_API_KEY: "vault-value"},
        )
        assert _severities(findings) == [Severity.FAIL]

    @pytest.mark.unit
    def test_in_chain_without_api_key_is_warning(self) -> None:
        """Нет API-ключа — предупреждение (секрет в Vault)."""
        findings = check_open_webui(
            {
                "ai_providers": {"fallback_chain": ["open_webui"]},
                "open_webui": {"base_url": "http://open-webui:3000"},
            },
            {},
        )
        assert _severities(findings) == [Severity.WARNING]

    @pytest.mark.unit
    def test_configured_but_not_in_chain_is_warning(self) -> None:
        """Сервис настроен, но провайдер не в цепочке — предупреждение."""
        findings = check_open_webui(
            {"ai_providers": {"fallback_chain": ["perplexity"]}},
            {ENV_OPEN_WEBUI_API_KEY: "vault-value"},
        )
        assert _severities(findings) == [Severity.WARNING]

    @pytest.mark.unit
    def test_not_deployed_is_warning(self) -> None:
        """Сервис не развёрнут — предупреждение (инфра-задача владельца)."""
        findings = check_open_webui(
            {"ai_providers": {"fallback_chain": ["perplexity"]}}, {}
        )
        assert _severities(findings) == [Severity.WARNING]


class TestJupyterHubCheck:
    """Пункт 5: JupyterHub."""

    @pytest.mark.unit
    def test_enabled_with_url_and_token_is_ok(self) -> None:
        """JupyterHub включён, URL и токен заданы — пункт закрыт."""
        findings = check_jupyter_hub(
            {"jupyter_hub": {"enabled": True, "base_url": "https://jupyter.internal"}},
            {ENV_JUPYTER_HUB_API_TOKEN: "vault-token"},
        )
        assert _severities(findings) == [Severity.OK]

    @pytest.mark.unit
    def test_enabled_without_base_url_fails(self) -> None:
        """Включён, но без URL — падение."""
        findings = check_jupyter_hub(
            {"jupyter_hub": {"enabled": True, "base_url": ""}},
            {ENV_JUPYTER_HUB_API_TOKEN: "vault-token"},
        )
        assert _severities(findings) == [Severity.FAIL]

    @pytest.mark.unit
    def test_enabled_with_loopback_url_fails(self) -> None:
        """Loopback в prod — это сам pod, а не JupyterHub — падение."""
        findings = check_jupyter_hub(
            {"jupyter_hub": {"enabled": True, "base_url": "http://localhost:8000"}},
            {ENV_JUPYTER_HUB_API_TOKEN: "vault-token"},
        )
        assert _severities(findings) == [Severity.FAIL]

    @pytest.mark.unit
    def test_enabled_without_token_is_warning(self) -> None:
        """Нет API-токена — предупреждение (секрет в Vault)."""
        findings = check_jupyter_hub(
            {"jupyter_hub": {"enabled": True, "base_url": "https://jupyter.internal"}},
            {},
        )
        assert _severities(findings) == [Severity.WARNING]

    @pytest.mark.unit
    def test_disabled_is_warning(self) -> None:
        """JupyterHub не развёрнут — предупреждение (инфра-задача владельца)."""
        findings = check_jupyter_hub({"jupyter_hub": {"enabled": False}}, {})
        assert _severities(findings) == [Severity.WARNING]

    @pytest.mark.unit
    def test_enabled_from_env(self) -> None:
        """Включение читается из env (JUPYTER_HUB_ENABLED)."""
        findings = check_jupyter_hub(
            {"jupyter_hub": {"enabled": False, "base_url": "https://jupyter.internal"}},
            {ENV_JUPYTER_HUB_ENABLED: "true", ENV_JUPYTER_HUB_API_TOKEN: "vault-token"},
        )
        assert _severities(findings) == [Severity.OK]


class TestReplicaDsnCheck:
    """Пункт 6: ``database.replica_dsn`` (null — допустимо)."""

    @pytest.mark.unit
    def test_null_is_ok(self) -> None:
        """``null`` — допустимое прод-значение (ADR-0407)."""
        findings = check_db_replica_dsn({"database": {"replica_dsn": None}}, {})
        assert _severities(findings) == [Severity.OK]

    @pytest.mark.unit
    def test_valid_dsn_is_ok(self) -> None:
        """Непустой DSN с реальным хостом — пункт закрыт."""
        findings = check_db_replica_dsn(
            {"database": {"replica_dsn": None}},
            {ENV_DB_REPLICA_DSN: "postgresql+asyncpg://u:p@pg-replica:5432/main_db"},
        )
        assert _severities(findings) == [Severity.OK]

    @pytest.mark.unit
    def test_loopback_dsn_fails(self) -> None:
        """Loopback-хост реплики — каждый pod писал бы в свой экземпляр."""
        findings = check_db_replica_dsn(
            {"database": {"replica_dsn": None}},
            {ENV_DB_REPLICA_DSN: "postgresql+asyncpg://u:p@127.0.0.1:5432/main_db"},
        )
        assert _severities(findings) == [Severity.FAIL]

    @pytest.mark.unit
    def test_non_dsn_value_fails(self) -> None:
        """Значение не является DSN — падение."""
        findings = check_db_replica_dsn(
            {"database": {"replica_dsn": "pg-replica:5432"}}, {}
        )
        assert _severities(findings) == [Severity.FAIL]

    @pytest.mark.unit
    def test_profile_value_used_without_env(self) -> None:
        """Значение берётся из профиля, если env не задан."""
        findings = check_db_replica_dsn(
            {
                "database": {
                    "replica_dsn": "postgresql+asyncpg://u:p@pg-replica:5432/main_db"
                }
            },
            {},
        )
        assert _severities(findings) == [Severity.OK]


class TestRegistryAndRunner:
    """Реестр проверок и общий прогон."""

    @pytest.mark.unit
    def test_all_six_checks_registered(self) -> None:
        """Чек-лист из 6 пунктов закрыт реестром проверок."""
        assert [check.id for check in INFRA_CHECKS] == [
            "jwks",
            "snapshot_service_role",
            "clickhouse",
            "open_webui",
            "jupyter_hub",
            "db_replica_dsn",
        ]

    @pytest.mark.unit
    def test_run_checks_covers_every_check(self) -> None:
        """Прогон возвращает результат по каждому пункту."""
        findings = run_checks({}, {})
        assert {finding.check for finding in findings} == {
            check.id for check in INFRA_CHECKS
        }

    @pytest.mark.unit
    def test_tool_does_not_import_app_config(self) -> None:
        """Гейт не тянет конфиг рантайма (Vault/сеть) — только YAML."""
        source = (
            Path(__file__).resolve().parents[3] / "tools" / "check_infra_readiness.py"
        ).read_text(encoding="utf-8")
        assert "src.backend" not in source


class TestProfileLoading:
    """Слияние ``base.yml`` + overlay профиля."""

    @pytest.mark.unit
    def test_overlay_wins(self, tmp_path: Path) -> None:
        """Значение профиля перекрывает базовое."""
        profiles = _write_profiles(
            tmp_path,
            base_yaml="security:\n  algorithm: HS256\n",
            prod_yaml="security:\n  algorithm: RS256\n",
        )
        merged = load_merged_profile("prod", profiles)
        assert merged["security"]["algorithm"] == "RS256"

    @pytest.mark.unit
    def test_missing_profile_raises(self, tmp_path: Path) -> None:
        """Отсутствующий профиль — ошибка запуска (exit 2)."""
        _write_profiles(tmp_path)
        with pytest.raises(FileNotFoundError):
            load_merged_profile("nosuchprofile", tmp_path)


class TestRealProdProfile:
    """Контракт гейта на реальном прод-профиле репозитория."""

    @pytest.mark.unit
    def test_prod_profile_has_sections_checked_by_gate(self) -> None:
        """Профиль prod содержит все секции, которые проверяет гейт."""
        merged = load_merged_profile("prod")
        for section in (
            "security",
            "snapshot",
            "clickhouse",
            "open_webui",
            "ai_providers",
            "jupyter_hub",
            "database",
            "features",
        ):
            assert section in merged, f"в prod-профиле нет секции {section!r}"

    @pytest.mark.unit
    def test_prod_profile_without_secrets_has_no_failures(self) -> None:
        """Конфигурация без секретов = предупреждения, а не падение."""
        findings = run_checks(load_merged_profile("prod"), {})
        failures = [f for f in findings if f.severity is Severity.FAIL]
        assert not failures, "; ".join(f.message for f in failures)


class TestCli:
    """CLI-контракт: exit codes 0/1/2, ``--strict`` и ``--json``."""

    @pytest.mark.unit
    def test_ready_profile_exits_zero(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Все пункты закрыты → exit 0."""
        profiles = _write_profiles(tmp_path)
        for name, value in READY_ENV.items():
            monkeypatch.setenv(name, value)
        assert main(["--profile", "prod", "--profiles-dir", str(profiles)]) == 0

    @pytest.mark.unit
    def test_violation_exits_one(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Нарушение (http:// в JWKS) → exit 1."""
        profiles = _write_profiles(tmp_path)
        for name, value in READY_ENV.items():
            monkeypatch.setenv(name, value)
        monkeypatch.setenv(ENV_JWKS_URL, "http://idp.internal/jwks.json")
        assert main(["--profile", "prod", "--profiles-dir", str(profiles)]) == 1

    @pytest.mark.unit
    def test_warning_does_not_block_by_default(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Предупреждение (OpenWebUI вне цепочки) не блокирует гейт."""
        profiles = _write_profiles(
            tmp_path, base_yaml=READY_BASE_YAML.replace('    - "open_webui"\n', "")
        )
        for name, value in READY_ENV.items():
            monkeypatch.setenv(name, value)
        assert main(["--profile", "prod", "--profiles-dir", str(profiles)]) == 0

    @pytest.mark.unit
    def test_strict_blocks_on_warning(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """``--strict`` блокирует гейт и на предупреждениях."""
        profiles = _write_profiles(
            tmp_path, base_yaml=READY_BASE_YAML.replace('    - "open_webui"\n', "")
        )
        for name, value in READY_ENV.items():
            monkeypatch.setenv(name, value)
        assert (
            main(["--profile", "prod", "--profiles-dir", str(profiles), "--strict"])
            == 1
        )

    @pytest.mark.unit
    def test_missing_profile_exits_two(self, tmp_path: Path) -> None:
        """Ошибка запуска (нет профиля) → exit 2."""
        profiles = _write_profiles(tmp_path)
        assert (
            main(["--profile", "nosuchprofile", "--profiles-dir", str(profiles)]) == 2
        )

    @pytest.mark.unit
    def test_json_output(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        capsys: pytest.CaptureFixture,
    ) -> None:
        """``--json`` печатает машинно-читаемый отчёт."""
        profiles = _write_profiles(tmp_path)
        for name, value in READY_ENV.items():
            monkeypatch.setenv(name, value)
        rc = main(["--profile", "prod", "--profiles-dir", str(profiles), "--json"])
        payload = json.loads(capsys.readouterr().out)
        assert rc == 0
        assert payload["profile"] == "prod"
        assert payload["ok"] is True
        assert payload["counts"]["fail"] == 0
        assert {item["id"] for item in payload["checks"]} == {
            check.id for check in INFRA_CHECKS
        }
