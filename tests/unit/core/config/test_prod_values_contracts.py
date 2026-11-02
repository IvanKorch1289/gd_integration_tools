"""ADR-0407 — контракты прод-значений конфигурации (волна 22, кластер B3).

Четыре owner-задачи из ``docs/roadmap/OWNER_TASKS.md`` § 3 («Прод-значения,
оставленные осознанно») закрыты исполняемыми контрактами, а не только
документацией:

1. **HS256 в prod.** Алгоритм подписи JWT в prod остаётся симметричным
   (``HS256``): переход на RS256 — отдельная owner-задача (нужна RSA-keypair
   + JWKS/IdP). Контракт: симметричный алгоритм допустим в prod **только**
   при гарантированном источнике JWT-секрета (``security.secret_key`` в
   YAML / env ``SEC_SECRET_KEY`` / Vault: ``vault.enabled`` + ``addr`` +
   ``secret_path``); без источника — CRITICAL
   (``security.jwt_symmetric_algorithm_without_secret``).

2. **WAF ``allow_hosts``.** В prod/staging при ``waf.strict=true`` allowlist
   обязан покрывать хосты всех внешних интеграций
   (``services/integrations/**``: СКБ-Техно, DaData) — иначе исходящий запрос
   блокируется (``WafBypassError``, strict-режим). Loopback-хост в allowlist
   допустим только когда в профиле есть локальная зависимость (sidecar
   ``clamd``) — иначе либо мёртвая запись, либо внешняя интеграция молча
   указывает на localhost (CRITICAL).

3. **AI fallback-chain.** В prod ``ai_providers.fallback_chain`` не должен
   содержать провайдера, недоступного в проде (``open_webui`` с
   loopback-``base_url``): откат на несуществующий сервис выглядит как
   «LLM отвечает» (CRITICAL ``ai_providers.fallback_chain_localhost``).

4. **``database.replica_dsn``.** ``null`` — «реплика не развёрнута», весь
   трафик идёт на primary; это **не** CRITICAL. Непустое значение — только
   реальный (не loopback) хост реплики; значение маскируется в дампах
   (ADR-0378 / ADR-0381).

Проверки — по merged-конфигу (``base.yml`` + overlay) и по результату
валидатора, а не по наличию строк в YAML-файле.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Final
from urllib.parse import urlparse

import pytest
import yaml

from src.backend.core.config.database import DatabaseConnectionSettings
from src.backend.core.config.validator import ConfigSeverity
from src.backend.core.config.validator.profile_merge import (
    merge_profile_yaml,
    validate_profile_config,
)
from src.backend.core.net.waf import WafPolicy

pytestmark = pytest.mark.unit

REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[4]
PROFILES_DIR: Final[Path] = REPO_ROOT / "config_profiles"

PROD_LIKE_PROFILES: Final[tuple[str, ...]] = ("prod", "staging")
"""Профили с прод-контрактами (ADR-0407)."""

JWT_VIOLATION: Final[str] = "security.jwt_symmetric_algorithm_without_secret"
WAF_COVERAGE_VIOLATION: Final[str] = "waf.allow_hosts_missing_integration_hosts"
WAF_LOOPBACK_VIOLATION: Final[str] = "waf.allow_hosts_loopback_without_local_dependency"
FALLBACK_VIOLATION: Final[str] = "ai_providers.fallback_chain_localhost"
REPLICA_VIOLATION: Final[str] = "database.replica_dsn_invalid"

EXTERNAL_INTEGRATION_ENDPOINTS: Final[tuple[tuple[str, str], ...]] = (
    ("skb", "prod_url"),
    ("dadata", "base_url"),
)
"""URL внешних интеграций из ``services/integrations/**``.

* ``skb.prod_url`` — ``src/backend/services/integrations/skb.py``
  (``SKBAPISettings.prod_url``, прод-контур; ``test_url`` в проде не
  используется — код читает только ``prod_url``/``base_url``);
* ``dadata.base_url`` — ``src/backend/services/integrations/dadata.py``
  (``DadataAPISettings.base_url``).
"""

LOOPBACK_HOSTS: Final[frozenset[str]] = frozenset(
    {"localhost", "127.0.0.1", "0.0.0.0", "::1", "0:0:0:0:0:0:0:1"}
)
"""Loopback-хосты (семейство, а не конкретный литерал)."""


def _load_yaml(path: Path) -> dict[str, Any]:
    """Читает YAML-файл профиля.

    Args:
        path: Путь к YAML-файлу.

    Returns:
        Разобранный mapping (пустой dict для пустого файла).
    """
    with path.open("r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    return data if isinstance(data, dict) else {}


def _merged(profile: str) -> dict[str, Any]:
    """Сливает ``base.yml`` + overlay профиля (как в рантайме).

    Args:
        profile: Имя профиля.

    Returns:
        Итоговый конфиг после слияния.
    """
    return merge_profile_yaml(profile)


def _copy_profiles(tmp_path: Path, profiles: tuple[str, ...]) -> Path:
    """Копирует ``base.yml`` + указанные профили во временный каталог.

    Args:
        tmp_path: Временный каталог pytest.
        profiles: Имена профилей для копирования.

    Returns:
        Путь к каталогу с профилями.
    """
    directory = tmp_path / "config_profiles"
    directory.mkdir(parents=True, exist_ok=True)
    for name in ("base.yml", *(f"{profile}.yml" for profile in profiles)):
        (directory / name).write_text(
            (PROFILES_DIR / name).read_text(encoding="utf-8"), encoding="utf-8"
        )
    return directory


def _patch_profile(
    directory: Path, profile: str, section: str, values: dict[str, Any]
) -> None:
    """Изменяет секцию профиля в подготовленном каталоге.

    Секция обновляется по ключам (остальные ключи сохраняются) — иначе
    merged-конфиг теряет обязательные поля и валидатор сообщает
    ``profile.incomplete`` вместо проверки контракта.

    Args:
        directory: Каталог профилей.
        profile: Имя профиля (``prod``/``staging``).
        section: Имя YAML-секции верхнего уровня.
        values: Значения секции (обновляются по ключам).
    """
    path = directory / f"{profile}.yml"
    data = _load_yaml(path)
    current = data.get(section)
    merged_section = dict(current) if isinstance(current, dict) else {}
    merged_section.update(values)
    data[section] = merged_section
    path.write_text(
        yaml.safe_dump(data, sort_keys=False, allow_unicode=True), encoding="utf-8"
    )


def _critical_codes(violations: tuple[Any, ...]) -> list[str]:
    """Коды CRITICAL-нарушений.

    Args:
        violations: Кортеж нарушений валидатора.

    Returns:
        Список кодов CRITICAL-нарушений.
    """
    return [
        violation.code
        for violation in violations
        if violation.severity == ConfigSeverity.CRITICAL
    ]


def _external_integration_urls(merged: dict[str, Any]) -> list[str]:
    """URL внешних интеграций из merged-конфига.

    Args:
        merged: Слияние ``base.yml`` + overlay профиля.

    Returns:
        Список URL внешних интеграций.
    """
    urls: list[str] = []
    for section, key in EXTERNAL_INTEGRATION_ENDPOINTS:
        url = (merged.get(section) or {}).get(key)
        if url:
            urls.append(str(url))
    return urls


def _external_integration_hosts(merged: dict[str, Any]) -> set[str]:
    """Хосты внешних интеграций из merged-конфига.

    Args:
        merged: Слияние ``base.yml`` + overlay профиля.

    Returns:
        Множество хостов (lowercase) внешних интеграций.
    """
    hosts: set[str] = set()
    for url in _external_integration_urls(merged):
        host = urlparse(url).hostname
        if host:
            hosts.add(host.lower())
    return hosts


class TestJwtAlgorithmContract:
    """HS256 в prod допустим только при гарантированном JWT-секрете."""

    def test_prod_without_secret_source_is_critical(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Prod без YAML/env/Vault-секрета — CRITICAL (проверка реально срабатывает)."""
        monkeypatch.delenv("SEC_SECRET_KEY", raising=False)
        profiles = _copy_profiles(tmp_path, ("prod",))
        _patch_profile(profiles, "prod", "vault", {"enabled": False})

        violations = validate_profile_config("prod", profiles)

        assert JWT_VIOLATION in _critical_codes(violations), (
            f"ожидался {JWT_VIOLATION}, получено {_critical_codes(violations)}"
        )

    def test_prod_with_env_secret_is_allowed(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Секрет в env (``SEC_SECRET_KEY``) — источник, CRITICAL нет."""
        monkeypatch.setenv("SEC_SECRET_KEY", "s" * 40)
        profiles = _copy_profiles(tmp_path, ("prod",))
        _patch_profile(profiles, "prod", "vault", {"enabled": False})

        violations = validate_profile_config("prod", profiles)

        assert JWT_VIOLATION not in _critical_codes(violations)

    def test_repo_prod_profile_has_no_critical_violations(self) -> None:
        """Штатный prod-профиль: 0 CRITICAL (секрет приходит из Vault)."""
        assert _critical_codes(validate_profile_config("prod")) == []

    def test_repo_prod_secret_source_is_declared(self) -> None:
        """Источник секрета prod объявлен явно: Vault включён, addr и secret_path заданы."""
        vault = _merged("prod")["vault"]

        assert vault["enabled"] is True
        assert str(vault["addr"]).strip()
        assert str(vault["secret_path"]).strip()

    def test_repo_prod_algorithm_is_symmetric_with_guarded_secret(self) -> None:
        """Текущая политика prod — симметричный алгоритм (HS256).

        Смена алгоритма на RS256 — owner-задача (нужна RSA-keypair + JWKS/IdP,
        ``docs/roadmap/OWNER_TASKS.md`` § 3.1); при её выполнении тест и
        ADR-0407 обновляются вместе с конфигом.
        """
        security = _merged("prod")["security"]

        assert str(security["algorithm"]).upper().startswith("HS")


class TestWafAllowlistContract:
    """Allowlist WAF покрывает внешние интеграции; loopback — только локальный."""

    @pytest.mark.parametrize("profile", PROD_LIKE_PROFILES)
    def test_allowlist_covers_external_integration_hosts(self, profile: str) -> None:
        """Хосты всех внешних интеграций есть в ``waf.allow_hosts``."""
        merged = _merged(profile)
        allowed = {str(host).lower() for host in merged["waf"]["allow_hosts"]}

        missing = _external_integration_hosts(merged) - allowed

        assert missing == set(), f"профиль {profile}: хосты вне allowlist: {missing}"

    @pytest.mark.parametrize("profile", PROD_LIKE_PROFILES)
    def test_outbound_request_to_integration_is_allowed(self, profile: str) -> None:
        """Проба WAF-политики: запрос к интеграции не блокируется."""
        merged = _merged(profile)
        policy = WafPolicy(
            allow_hosts=frozenset(merged["waf"]["allow_hosts"]),
            deny_hosts=frozenset(merged["waf"]["deny_hosts"]),
            strict=merged["waf"]["strict"],
        )

        blocked = [
            url
            for url in _external_integration_urls(merged)
            if not policy.evaluate(url).allowed
        ]

        assert blocked == [], f"профиль {profile}: WAF блокирует: {blocked}"

    @pytest.mark.parametrize("profile", PROD_LIKE_PROFILES)
    def test_repo_profiles_have_no_waf_critical(self, profile: str) -> None:
        """Валидатор не находит нарушений WAF-контракта в репозиторных профилях."""
        codes = _critical_codes(validate_profile_config(profile))

        assert WAF_COVERAGE_VIOLATION not in codes
        assert WAF_LOOPBACK_VIOLATION not in codes

    def test_missing_integration_host_is_critical(self, tmp_path: Path) -> None:
        """Интеграция вне allowlist при strict=true — CRITICAL."""
        profiles = _copy_profiles(tmp_path, ("prod",))
        _patch_profile(
            profiles,
            "prod",
            "waf",
            {"allow_hosts": ["esbgreendata", "localhost", "127.0.0.1"]},
        )

        codes = _critical_codes(validate_profile_config("prod", profiles))

        assert WAF_COVERAGE_VIOLATION in codes, (
            f"ожидался {WAF_COVERAGE_VIOLATION}, получено {codes}"
        )

    def test_loopback_without_local_dependency_is_critical(
        self, tmp_path: Path
    ) -> None:
        """Loopback в allowlist без локальной зависимости (clamd выключен) — CRITICAL."""
        profiles = _copy_profiles(tmp_path, ("prod",))
        _patch_profile(
            profiles,
            "prod",
            "waf",
            {
                "allow_hosts": [
                    "esbgreendata",
                    "localhost",
                    "127.0.0.1",
                    "api.skb-techno.ru",
                    "suggestions.dadata.ru",
                ],
                "clamav_enabled": False,
            },
        )

        codes = _critical_codes(validate_profile_config("prod", profiles))

        assert WAF_LOOPBACK_VIOLATION in codes, (
            f"ожидался {WAF_LOOPBACK_VIOLATION}, получено {codes}"
        )

    @pytest.mark.parametrize("profile", PROD_LIKE_PROFILES)
    def test_loopback_entry_is_justified_by_local_dependency(
        self, profile: str
    ) -> None:
        """Loopback-запись оправдана локальным sidecar'ом (clamd на loopback)."""
        merged = _merged(profile)
        waf = merged["waf"]
        loopback_entries = [
            host
            for host in waf["allow_hosts"]
            if str(host).strip().lower() in LOOPBACK_HOSTS
        ]

        if not loopback_entries:
            pytest.skip("в allowlist нет loopback-записей — контракт не нарушен")

        assert waf["clamav_enabled"] is True
        assert str(waf["clamav_host"]).strip().lower() in LOOPBACK_HOSTS


class TestAiFallbackChainContract:
    """Fallback-цепочка AI в prod не содержит недоступных сервисов."""

    def test_prod_chain_has_no_unavailable_provider(self) -> None:
        """Ни один провайдер prod-цепочки не указывает на loopback."""
        merged = _merged("prod")
        chain = merged["ai_providers"]["fallback_chain"]

        assert "open_webui" not in chain

        unavailable = [
            provider
            for provider in chain
            if str(
                urlparse(
                    str((merged.get(provider) or {}).get("base_url") or "")
                ).hostname
                or ""
            ).lower()
            in LOOPBACK_HOSTS
        ]

        assert unavailable == [], f"недоступные в prod провайдеры: {unavailable}"

    def test_repo_prod_profile_has_no_fallback_critical(self) -> None:
        """Валидатор prod-профиля не находит нарушений AI-fallback."""
        assert FALLBACK_VIOLATION not in _critical_codes(
            validate_profile_config("prod")
        )

    def test_unavailable_provider_in_chain_is_critical(self, tmp_path: Path) -> None:
        """``open_webui`` (localhost) в prod-цепочке — CRITICAL."""
        profiles = _copy_profiles(tmp_path, ("prod",))
        _patch_profile(
            profiles,
            "prod",
            "ai_providers",
            {"fallback_chain": ["perplexity", "open_webui", "openai"]},
        )

        codes = _critical_codes(validate_profile_config("prod", profiles))

        assert FALLBACK_VIOLATION in codes, (
            f"ожидался {FALLBACK_VIOLATION}, получено {codes}"
        )


class TestReplicaDsnContract:
    """``database.replica_dsn``: null допустим, непустое значение — реальный хост."""

    @pytest.mark.parametrize("profile", PROD_LIKE_PROFILES)
    def test_null_replica_dsn_is_not_critical(self, profile: str) -> None:
        """``replica_dsn: null`` («реплики нет») — не CRITICAL."""
        merged = _merged(profile)

        assert (merged.get("database") or {}).get("replica_dsn") is None
        assert REPLICA_VIOLATION not in _critical_codes(
            validate_profile_config(profile)
        )

    def test_loopback_replica_dsn_is_critical(self, tmp_path: Path) -> None:
        """Реплика на loopback — CRITICAL (каждый pod получил бы свой экземпляр)."""
        profiles = _copy_profiles(tmp_path, ("prod",))
        _patch_profile(
            profiles,
            "prod",
            "database",
            {"replica_dsn": "postgresql+asyncpg://user:pwd@127.0.0.1:5432/main_db"},
        )

        codes = _critical_codes(validate_profile_config("prod", profiles))

        assert REPLICA_VIOLATION in codes, (
            f"ожидался {REPLICA_VIOLATION}, получено {codes}"
        )

    def test_replica_dsn_without_host_is_critical(self, tmp_path: Path) -> None:
        """Непустое значение без хоста — CRITICAL (реальный хост обязателен)."""
        profiles = _copy_profiles(tmp_path, ("prod",))
        _patch_profile(profiles, "prod", "database", {"replica_dsn": "not-a-dsn"})

        codes = _critical_codes(validate_profile_config("prod", profiles))

        assert REPLICA_VIOLATION in codes, (
            f"ожидался {REPLICA_VIOLATION}, получено {codes}"
        )

    def test_real_replica_host_is_allowed(self, tmp_path: Path) -> None:
        """Реплика с реальным host'ом — нарушений нет."""
        profiles = _copy_profiles(tmp_path, ("prod",))
        _patch_profile(
            profiles,
            "prod",
            "database",
            {"replica_dsn": "postgresql+asyncpg://user:pwd@pg-replica:5432/main_db"},
        )

        assert REPLICA_VIOLATION not in _critical_codes(
            validate_profile_config("prod", profiles)
        )

    def test_non_empty_replica_dsn_is_masked_in_dumps(self) -> None:
        """Непустой DSN реплики маскируется в дампах (ADR-0378 / ADR-0381)."""
        settings = DatabaseConnectionSettings(
            type="postgresql",
            username="user",
            password="pwd",
            host="localhost",
            port=5432,
            name="mydb",
            async_driver="asyncpg",
            sync_driver="psycopg",
            ssl_mode=None,
            ca_bundle=None,
            replica_dsn="postgresql+asyncpg://replica:s3cr3t@pg-replica:5432/main_db",
        )

        dumped = settings.model_dump()

        assert "s3cr3t" not in str(dumped)
        assert "***" in str(dumped["replica_dsn"])
