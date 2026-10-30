"""ADR-0400: профильный гейт интроспекции GraphQL.

Ключ ``graphql.enable_introspection`` декларативен (``base.yml`` + overlay
профиля), но до ADR-0400 его значение никто не проверял: «выключено в
конфиге» и «разрешено в рантайме» могли разойтись, а
``graphql_guards`` смотрел только на окружение.

Политика: в prod/staging интроспекция — recon-поверхность, поэтому
``graphql.enable_introspection: true`` — CRITICAL-нарушение профиля.
"""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from src.backend.core.config.validator import ConfigSeverity
from src.backend.core.config.validator.profile_merge import validate_profile_config

pytestmark = pytest.mark.unit

REPO_ROOT = Path(__file__).resolve().parents[4]
PROFILES_DIR = REPO_ROOT / "config_profiles"

_VIOLATION_CODE = "graphql.introspection_enabled_in_prod"


def _write_profiles(directory: Path, *, enable_introspection: bool) -> Path:
    """Создать каталог профилей на основе репозиторных base/prod.

    Args:
        directory: Каталог для ``config_profiles``.
        enable_introspection: Значение ``graphql.enable_introspection``.

    Returns:
        Путь к каталогу профилей.
    """
    base = yaml.safe_load((PROFILES_DIR / "base.yml").read_text()) or {}
    prod = yaml.safe_load((PROFILES_DIR / "prod.yml").read_text()) or {}
    base.setdefault("graphql", {})["enable_introspection"] = enable_introspection
    prod.setdefault("graphql", {})["enable_introspection"] = enable_introspection
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "base.yml").write_text(
        yaml.safe_dump(base, sort_keys=False, allow_unicode=True), encoding="utf-8"
    )
    (directory / "prod.yml").write_text(
        yaml.safe_dump(prod, sort_keys=False, allow_unicode=True), encoding="utf-8"
    )
    return directory


@pytest.mark.parametrize("profile", ("prod", "staging"))
def test_repo_profiles_have_introspection_disabled(profile: str) -> None:
    """Штатные prod/staging-профили: интроспекция выключена, CRITICAL нет."""
    violations = validate_profile_config(profile)
    critical = [
        violation.code
        for violation in violations
        if violation.severity == ConfigSeverity.CRITICAL
    ]
    assert critical == [], f"профиль {profile}: CRITICAL-нарушения: {critical}"


def test_introspection_enabled_in_prod_is_critical(tmp_path: Path) -> None:
    """``graphql.enable_introspection: true`` в prod — CRITICAL."""
    profiles = _write_profiles(tmp_path / "config_profiles", enable_introspection=True)

    violations = validate_profile_config("prod", profiles)

    critical = [
        violation.code
        for violation in violations
        if violation.severity == ConfigSeverity.CRITICAL
    ]
    assert _VIOLATION_CODE in critical, (
        f"ожидалось {_VIOLATION_CODE}, получено {critical}"
    )


def test_introspection_enabled_in_dev_is_allowed(tmp_path: Path) -> None:
    """В dev интроспекция разрешена — нарушения нет."""
    profiles = _write_profiles(tmp_path / "config_profiles", enable_introspection=True)
    (profiles / "dev.yml").write_text(
        yaml.safe_dump({"app": {"environment": "development"}}, sort_keys=False),
        encoding="utf-8",
    )

    violations = validate_profile_config("dev", profiles)

    assert not any(violation.code == _VIOLATION_CODE for violation in violations)
