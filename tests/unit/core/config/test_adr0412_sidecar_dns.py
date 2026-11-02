"""ADR-0412 — service-DNS для sidecar'ов и endpoint-контракты (волна 23, C2).

Контракт ADR-0412: в prod/staging sidecar'ы (``clamd``, ``otel-collector``)
и внутренние endpoint'ы (``OpenWebUI``) адресуются по service-DNS, а не по
loopback. В k8s ``127.0.0.1`` — это сам pod, а не соседний контейнер:
loopback-хост в конфиге означает молчаливый обход к самому себе ( clamd не
сканирует payload, телеметрия не уходит, LLM-запрос уходит в никуда).

Проверки:

* валидатор merged-профиля: loopback-хост sidecar'а в prod/staging —
  CRITICAL; service-DNS — OK;
* ключи конфигурации (модель ↔ YAML): каждый затронутый YAML-ключ есть в
  pydantic-модели, env-имя выводится из env-префикса модели;
* значения по умолчанию (``config_profiles/base.yml``) — service-DNS имена.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Final
from urllib.parse import urlparse

import pytest
import yaml

from src.backend.core.config.ai import OpenWebUISettings
from src.backend.core.config.base import AppBaseSettings
from src.backend.core.config.database import DatabaseConnectionSettings
from src.backend.core.config.validator import ConfigSeverity
from src.backend.core.config.validator.profile_merge import (
    merge_profile_yaml,
    validate_profile_config,
)
from src.backend.core.config.waf import WafSettings

pytestmark = pytest.mark.unit

REPO_ROOT: Final[Path] = Path(__file__).resolve().parents[4]
PROFILES_DIR: Final[Path] = REPO_ROOT / "config_profiles"

PROD_LIKE_PROFILES: Final[tuple[str, ...]] = ("prod", "staging")
"""Профили с прод-контрактами значений (ADR-0407, ADR-0412)."""

CLAMAV_VIOLATION: Final[str] = "waf.clamav_host_loopback_in_prod"
OTEL_VIOLATION: Final[str] = "app.opentelemetry_endpoint_loopback_in_prod"

CLAMAV_SERVICE_NAME: Final[str] = "clamd"
"""Service-DNS имя sidecar'а ClamAV (k8s Service ``clamd``)."""

OTEL_SERVICE_NAME: Final[str] = "otel-collector"
"""Service-DNS имя OTel-collector'а (k8s Service ``otel-collector``)."""

OPEN_WEBUI_SERVICE_NAME: Final[str] = "open-webui"
"""Service-DNS имя внутреннего OpenWebUI (k8s Service ``open-webui``)."""

REPLICA_DSN_TEMPLATE: Final[str] = (
    "postgresql+asyncpg://<user>:<pass>@<replica-host>:5432/<db>"
)
"""Шаблон DSN read-реплики (документируется, значение остаётся ``null``)."""


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


def _host(value: str) -> str:
    """Хост endpoint'а (URL или голый host).

    Args:
        value: Значение endpoint'а.

    Returns:
        Хост в нижнем регистре (пустая строка — хост не разобран).
    """
    text = str(value).strip()
    if not text:
        return ""
    if "://" in text:
        return (urlparse(text).hostname or "").lower()
    return text.split(":", 1)[0].strip().lower()


class TestSidecarHostValidator:
    """Sidecar'ы в prod/staging адресуются по service-DNS, не по loopback."""

    @pytest.mark.parametrize("profile", PROD_LIKE_PROFILES)
    def test_repo_profile_has_no_sidecar_critical(self, profile: str) -> None:
        """Репозиторный prod/staging-профиль: sidecar-нарушений нет."""
        codes = _critical_codes(validate_profile_config(profile))

        assert CLAMAV_VIOLATION not in codes
        assert OTEL_VIOLATION not in codes

    @pytest.mark.parametrize("profile", PROD_LIKE_PROFILES)
    def test_clamav_loopback_host_is_critical(
        self, tmp_path: Path, profile: str
    ) -> None:
        """Включённый clamd на loopback в prod/staging — CRITICAL."""
        profiles = _copy_profiles(tmp_path, (profile,))
        _patch_profile(
            profiles,
            profile,
            "waf",
            {"clamav_enabled": True, "clamav_host": "127.0.0.1"},
        )

        codes = _critical_codes(validate_profile_config(profile, profiles))

        assert CLAMAV_VIOLATION in codes, (
            f"ожидался {CLAMAV_VIOLATION}, получено {codes}"
        )

    def test_clamav_disabled_skips_loopback_check(self, tmp_path: Path) -> None:
        """Выключенный clamd не обязан иметь service-DNS-хост."""
        profiles = _copy_profiles(tmp_path, ("prod",))
        _patch_profile(
            profiles,
            "prod",
            "waf",
            {"clamav_enabled": False, "clamav_host": "127.0.0.1"},
        )

        codes = _critical_codes(validate_profile_config("prod", profiles))

        assert CLAMAV_VIOLATION not in codes

    def test_otel_loopback_endpoint_is_critical(self, tmp_path: Path) -> None:
        """OTel-экспорт на loopback в prod — CRITICAL."""
        profiles = _copy_profiles(tmp_path, ("prod",))
        _patch_profile(
            profiles, "prod", "app", {"opentelemetry_endpoint": "http://127.0.0.1:4317"}
        )

        codes = _critical_codes(validate_profile_config("prod", profiles))

        assert OTEL_VIOLATION in codes, f"ожидался {OTEL_VIOLATION}, получено {codes}"

    def test_service_dns_hosts_are_accepted(self, tmp_path: Path) -> None:
        """service-DNS-хосты sidecar'ов — без нарушений."""
        profiles = _copy_profiles(tmp_path, ("prod",))
        _patch_profile(
            profiles,
            "prod",
            "waf",
            {"clamav_enabled": True, "clamav_host": CLAMAV_SERVICE_NAME},
        )
        _patch_profile(
            profiles,
            "prod",
            "app",
            {"opentelemetry_endpoint": f"http://{OTEL_SERVICE_NAME}:4317"},
        )

        codes = _critical_codes(validate_profile_config("prod", profiles))

        assert CLAMAV_VIOLATION not in codes
        assert OTEL_VIOLATION not in codes


class TestConfigKeysModelYaml:
    """Затронутые YAML-ключи существуют в моделях, значения — service-DNS."""

    YAML_KEYS: Final[tuple[tuple[str, type[Any], str], ...]] = (
        ("waf.clamav_host", WafSettings, "clamav_host"),
        ("app.opentelemetry_endpoint", AppBaseSettings, "opentelemetry_endpoint"),
        ("open_webui.base_url", OpenWebUISettings, "base_url"),
        ("database.replica_dsn", DatabaseConnectionSettings, "replica_dsn"),
    )
    """Путь в YAML → (модель, поле модели)."""

    def test_yaml_keys_exist_in_models(self) -> None:
        """Каждый затронутый YAML-ключ — поле pydantic-модели."""
        for path, model, field in self.YAML_KEYS:
            assert field in model.model_fields, f"{path}: нет поля {field} в {model}"

    def test_env_names_derive_from_model_prefix(self) -> None:
        """env-имена выводятся из env-префикса моделей (для deploy-манифестов)."""
        assert WafSettings.model_config.get("env_prefix") == "WAF_"
        assert AppBaseSettings.model_config.get("env_prefix") == "APP_"
        assert DatabaseConnectionSettings.model_config.get("env_prefix") == "DB_"

    def test_base_defaults_are_service_dns(self) -> None:
        """Дефолты base.yml — service-DNS имена (ADR-0412)."""
        base = _load_yaml(PROFILES_DIR / "base.yml")

        assert base["waf"]["clamav_host"] == CLAMAV_SERVICE_NAME
        assert _host(base["app"]["opentelemetry_endpoint"]) == OTEL_SERVICE_NAME
        assert _host(base["open_webui"]["base_url"]) == OPEN_WEBUI_SERVICE_NAME

    @pytest.mark.parametrize("profile", PROD_LIKE_PROFILES)
    def test_profile_values_are_service_dns(self, profile: str) -> None:
        """prod/staging: sidecar'ы и OpenWebUI — по service-DNS."""
        merged = _merged(profile)

        assert _host(merged["waf"]["clamav_host"]) == CLAMAV_SERVICE_NAME
        assert _host(merged["app"]["opentelemetry_endpoint"]) == OTEL_SERVICE_NAME
        assert _host(merged["open_webui"]["base_url"]) == OPEN_WEBUI_SERVICE_NAME

    @pytest.mark.parametrize("profile", PROD_LIKE_PROFILES)
    def test_prod_chain_excludes_open_webui(self, profile: str) -> None:
        """OpenWebUI не возвращён в fallback-цепочку до развёртывания сервиса."""
        chain = _merged(profile)["ai_providers"]["fallback_chain"]

        assert "open_webui" not in chain

    @pytest.mark.parametrize("profile", PROD_LIKE_PROFILES)
    def test_replica_dsn_stays_null(self, profile: str) -> None:
        """``replica_dsn`` остаётся ``null`` — факт «реплики нет»."""
        merged = _merged(profile)

        assert (merged.get("database") or {}).get("replica_dsn") is None

    @pytest.mark.parametrize("profile", ("base", "prod", "staging"))
    def test_replica_dsn_template_documented(self, profile: str) -> None:
        """Шаблон DSN реплики задокументирован в комментарии профиля."""
        text = (PROFILES_DIR / f"{profile}.yml").read_text(encoding="utf-8")

        assert REPLICA_DSN_TEMPLATE in text

    def test_replica_dsn_template_documented_in_guide(self) -> None:
        """Шаблон DSN реплики задокументирован в SETTINGS_GUIDE."""
        guide = (REPO_ROOT / "docs" / "config" / "SETTINGS_GUIDE.md").read_text(
            encoding="utf-8"
        )

        assert REPLICA_DSN_TEMPLATE in guide
