"""A9 (ADR-0385): ``validate-profile`` валидирует секции БД.

Дефект
------
``core/config/validator/profile_merge.py`` собирал ``ProfileSettings``
через ``model_construct`` (без валидации), а секция ``external_databases``
не была известна валидатору вообще. Поэтому битые значения
(``pool_size: 0``, ``port: 99999``, опечатка в подключении) проходили
с exit 0 — конфиг падал только в рантайме.

Ожидание
--------
* ``database`` валидируется моделью (:class:`DatabaseConnectionSettings`);
* ``external_databases`` — моделью :class:`ExternalDatabasesSettings`;
* нарушение → CRITICAL (exit 1 у ``manage.py validate-profile``);
* штатные профили репозитория остаются зелёными.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

from src.backend.core.config.validator import ConfigSeverity
from src.backend.core.config.validator.profile_merge import validate_profile_config

pytestmark = pytest.mark.unit

REPO_ROOT = Path(__file__).resolve().parents[4]
PROFILES_DIR = REPO_ROOT / "config_profiles"


def _profiles_dir(tmp_path: Path) -> Path:
    """Копия репозиторных ``base.yml`` + ``dev.yml`` во временный каталог.

    Копии нужны, чтобы merged-конфиг был полным (иначе ``ConfigValidator``
    сообщает ``profile.incomplete`` вместо проверки секций БД).

    Returns:
        Путь к каталогу профилей.
    """
    directory = tmp_path / "config_profiles"
    directory.mkdir(parents=True, exist_ok=True)
    for name in ("base.yml", "dev.yml"):
        (directory / name).write_text(
            (PROFILES_DIR / name).read_text(encoding="utf-8"), encoding="utf-8"
        )
    return directory


def _patch_section(directory: Path, section: str, values: dict[str, Any]) -> None:
    """Обновить секцию overlay-файла ``dev.yml`` (merged-значения берутся оттуда)."""
    path = directory / "dev.yml"
    data = yaml.safe_load(path.read_text()) or {}
    data[section] = {**(data.get(section) or {}), **values}
    path.write_text(
        yaml.safe_dump(data, sort_keys=False, allow_unicode=True), encoding="utf-8"
    )


def _critical_codes(violations: Any) -> list[str]:
    return [
        violation.code
        for violation in violations
        if violation.severity == ConfigSeverity.CRITICAL
    ]


class TestDatabaseSectionValidation:
    """Секция ``database`` валидируется моделью."""

    def test_invalid_pool_size_is_critical(self, tmp_path: Path) -> None:
        """``pool_size: 0`` (ge=1) — CRITICAL."""
        directory = _profiles_dir(tmp_path)
        _patch_section(directory, "database", {"pool_size": 0})
        violations = validate_profile_config("dev", directory)
        assert "database.invalid" in _critical_codes(violations)

    def test_invalid_port_is_critical(self, tmp_path: Path) -> None:
        """``port: 99999`` (lt=65536) — CRITICAL."""
        directory = _profiles_dir(tmp_path)
        _patch_section(directory, "database", {"port": 99999})
        violations = validate_profile_config("dev", directory)
        assert "database.invalid" in _critical_codes(violations)

    def test_unknown_database_key_is_critical(self, tmp_path: Path) -> None:
        """Опечатка в ключе секции ``database`` — CRITICAL (extra=forbid)."""
        directory = _profiles_dir(tmp_path)
        _patch_section(directory, "database", {"pool_sze": 5})
        violations = validate_profile_config("dev", directory)
        assert "database.invalid" in _critical_codes(violations)

    def test_valid_database_section_passes(self, tmp_path: Path) -> None:
        """Корректные значения секции не дают нарушений."""
        directory = _profiles_dir(tmp_path)
        _patch_section(directory, "database", {"pool_size": 5, "port": 5432})
        violations = validate_profile_config("dev", directory)
        assert "database.invalid" not in _critical_codes(violations)


class TestExternalDatabasesSectionValidation:
    """Секция ``external_databases`` валидируется моделью."""

    def test_unknown_connection_key_is_critical(self, tmp_path: Path) -> None:
        """Опечатка в подключении (``sslmode``) — CRITICAL."""
        directory = _profiles_dir(tmp_path)
        _patch_section(
            directory,
            "external_databases",
            {
                "connections": [
                    {
                        "name": "pg_1",
                        "profile_name": "pg_1",
                        "type": "postgresql",
                        "host": "10.10.20.21",
                        "port": 5432,
                        "db_name": "analytics",
                        "async_driver": "asyncpg",
                        "sync_driver": "psycopg",
                        "schema": "public",
                        "sslmode": "require",
                    }
                ]
            },
        )
        violations = validate_profile_config("dev", directory)
        assert "external_databases.invalid" in _critical_codes(violations)

    def test_invalid_connection_pool_size_is_critical(self, tmp_path: Path) -> None:
        """``pool_size: 0`` в подключении — CRITICAL."""
        directory = _profiles_dir(tmp_path)
        _patch_section(
            directory,
            "external_databases",
            {
                "connections": [
                    {
                        "name": "pg_1",
                        "profile_name": "pg_1",
                        "type": "postgresql",
                        "host": "10.10.20.21",
                        "port": 5432,
                        "db_name": "analytics",
                        "async_driver": "asyncpg",
                        "sync_driver": "psycopg",
                        "schema": "public",
                        "pool_size": 0,
                    }
                ]
            },
        )
        violations = validate_profile_config("dev", directory)
        assert "external_databases.invalid" in _critical_codes(violations)


class TestRepositoryProfilesStayGreen:
    """Штатные профили репозитория не ломаются новой валидацией."""

    @pytest.mark.parametrize("profile", ("dev", "dev_light", "staging", "prod"))
    def test_no_db_section_violations(self, profile: str) -> None:
        """Секции БД штатных профилей валидны."""
        violations = validate_profile_config(profile)
        codes = _critical_codes(violations)
        assert "database.invalid" not in codes
        assert "external_databases.invalid" not in codes
