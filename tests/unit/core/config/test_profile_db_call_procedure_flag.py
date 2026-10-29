"""ADR-0389: инвариант профиля для feature-флага ``db_call_procedure_enabled``.

Дефект (до фикса)
-----------------
Флаг ``db_call_procedure_enabled`` — default-OFF (ADR-0380), а профиль с
внешними БД (``external_databases.connections[]``) может при этом остаться
«зелёным» в ``manage.py validate-profile``: оператор узнавал о выключенном
шаге только в рантайме, когда процедура молча не вызывалась.

Ожидание
--------
* профиль объявляет внешнюю БД, а флаг выключен → **WARNING** (не CRITICAL:
  профиль может быть внешней БД вовсе без вызовов процедур);
* флаг включён → нарушения нет;
* внешних БД нет → нарушения нет;
* код нарушения — ``feature_flag.db_call_procedure_disabled``.
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

VIOLATION_CODE = "feature_flag.db_call_procedure_disabled"


def _profiles_dir(tmp_path: Path, *names: str) -> Path:
    """Копия репозиторных профилей во временный каталог.

    Копии нужны, чтобы merged-конфиг был полным (иначе валидатор сообщает
    ``profile.incomplete`` вместо проверки инвариантов).

    Args:
        tmp_path: Временный каталог pytest.
        names: Имена профилей (``base.yml`` копируется всегда).

    Returns:
        Путь к каталогу профилей.

    """
    directory = tmp_path / "config_profiles"
    directory.mkdir(parents=True, exist_ok=True)
    for name in ("base.yml", *names):
        (directory / name).write_text(
            (PROFILES_DIR / name).read_text(encoding="utf-8"), encoding="utf-8"
        )
    return directory


def _patch_features(directory: Path, values: dict[str, Any]) -> None:
    """Обновить секцию ``features`` overlay-файла ``dev.yml``."""
    path = directory / "dev.yml"
    data = yaml.safe_load(path.read_text()) or {}
    data["features"] = {**(data.get("features") or {}), **values}
    path.write_text(
        yaml.safe_dump(data, sort_keys=False, allow_unicode=True), encoding="utf-8"
    )


def _violations(profile: str, directory: Path) -> list[Any]:
    """Нарушения профиля по конкретному коду."""
    return [
        violation
        for violation in validate_profile_config(profile, directory)
        if violation.code == VIOLATION_CODE
    ]


class TestDbCallProcedureFlagInvariant:
    """Профиль с внешней БД + выключенный флаг → WARNING."""

    def test_external_db_with_flag_off_is_warning(self, tmp_path: Path) -> None:
        """Внешняя БД объявлена, флаг выключен — WARNING (не CRITICAL)."""
        directory = _profiles_dir(tmp_path, "dev.yml")
        violations = _violations("dev", directory)
        assert violations, "профиль с внешней БД и выключенным флагом → WARNING"
        violation = violations[0]
        assert violation.severity == ConfigSeverity.WARNING
        assert "db_call_procedure_enabled" in violation.message

    def test_flag_on_has_no_violation(self, tmp_path: Path) -> None:
        """Флаг включён — нарушения нет."""
        directory = _profiles_dir(tmp_path, "dev.yml")
        _patch_features(directory, {"db_call_procedure_enabled": True})
        assert _violations("dev", directory) == []

    def test_profile_without_external_db_has_no_violation(
        self, tmp_path: Path
    ) -> None:
        """Внешних БД нет — нарушения нет (dev_light: ``connections: []``)."""
        directory = _profiles_dir(tmp_path, "dev_light.yml")
        assert _violations("dev_light", directory) == []

    def test_repo_profiles_are_consistent(self) -> None:
        """Инвариант держится на штатных профилях репозитория.

        Каждый профиль с внешними БД обязан явно включать флаг — иначе
        вызовы процедур будут пропущены без ошибки.
        """
        for profile in ("dev", "dev_light", "staging", "prod"):
            path = PROFILES_DIR / f"{profile}.yml"
            if not path.is_file():
                continue
            data = yaml.safe_load(path.read_text()) or {}
            connections = (data.get("external_databases") or {}).get("connections") or []
            flags = (data.get("features") or {}).get("db_call_procedure_enabled")
            if connections and not flags:
                assert _violations(profile, PROFILES_DIR), (
                    f"профиль {profile}: внешняя БД объявлена, флаг выключен — "
                    "ожидается WARNING"
                )
            else:
                assert _violations(profile, PROFILES_DIR) == []
