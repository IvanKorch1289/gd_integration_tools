"""ADR-0393 — политика capability-гейта в профилях prod/staging.

Волна 18 (дефект 9): capability-гейт был включён только в dev/dev_light,
а в prod/staging действовал legacy-путь (deny-all без внятной причины).
Теперь политика объявлена ЯВНО и проверяется валидатором профиля:

* ``features.dsl_capability_gate_enabled`` в prod/staging обязан быть
  ``true`` (иначе — CRITICAL: БД/RPA-шаги не авторизуются);
* ``features.dsl_capability_core_baseline_enabled`` обязан быть ``false``
  (иначе — WARNING: least-privilege нарушен, capability ядра выдаётся всем).
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest
import yaml

from src.backend.core.config.validator import ConfigSeverity
from src.backend.core.config.validator.profile_merge import (
    merge_profile_yaml,
    validate_profile_config,
)

pytestmark = pytest.mark.unit

REPO_ROOT = Path(__file__).resolve().parents[4]
PROFILES_DIR = REPO_ROOT / "config_profiles"


@pytest.mark.parametrize("profile", ("prod", "staging"))
def test_capability_gate_enabled_in_prod_like_profiles(profile: str) -> None:
    """В prod/staging capability-гейт включён (ADR-0393)."""
    merged = merge_profile_yaml(profile, PROFILES_DIR)
    features = merged.get("features") or {}

    assert features.get("dsl_capability_gate_enabled") is True
    assert features.get("dsl_capability_core_baseline_enabled") is False


@pytest.mark.parametrize("profile", ("prod", "staging"))
def test_profile_validation_has_no_capability_violations(profile: str) -> None:
    """Профили prod/staging проходят проверку политики capability-гейта."""
    violations = validate_profile_config(profile, PROFILES_DIR)
    codes = {violation.code for violation in violations}

    assert "feature_flag.dsl_capability_gate_disabled" not in codes
    assert "feature_flag.dsl_capability_core_baseline_enabled" not in codes


def _write_profile(
    directory: Path, *, gate: bool | None, baseline: bool | None
) -> Path:
    """Создать временный каталог профилей с заданными флагами.

    Берётся **настоящий** base.yml + prod.yml (иначе merged-конфиг не
    проходит общие проверки профиля), меняются только capability-флаги.
    """
    directory.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(PROFILES_DIR / "base.yml", directory / "base.yml")
    overlay = yaml.safe_load((PROFILES_DIR / "prod.yml").read_text(encoding="utf-8"))
    features = overlay.setdefault("features", {})
    assert isinstance(features, dict)
    if gate is not None:
        features["dsl_capability_gate_enabled"] = gate
    if baseline is not None:
        features["dsl_capability_core_baseline_enabled"] = baseline
    (directory / "prod.yml").write_text(
        yaml.safe_dump(overlay, allow_unicode=True), encoding="utf-8"
    )
    return directory


def test_disabled_capability_gate_in_prod_is_critical(tmp_path: Path) -> None:
    """Выключенный capability-гейт в prod → CRITICAL (ADR-0393)."""
    profiles = _write_profile(tmp_path / "profiles", gate=False, baseline=False)

    violations = validate_profile_config("prod", profiles)
    critical = [
        violation
        for violation in violations
        if violation.code == "feature_flag.dsl_capability_gate_disabled"
    ]

    assert critical
    assert critical[0].severity == ConfigSeverity.CRITICAL


def test_enabled_core_baseline_in_prod_is_warning(tmp_path: Path) -> None:
    """Включённый core-baseline в prod → WARNING (least privilege)."""
    profiles = _write_profile(tmp_path / "profiles", gate=True, baseline=True)

    violations = validate_profile_config("prod", profiles)
    warnings = [
        violation
        for violation in violations
        if violation.code == "feature_flag.dsl_capability_core_baseline_enabled"
    ]

    assert warnings
    assert warnings[0].severity == ConfigSeverity.WARNING


def test_capability_policy_not_checked_in_dev(tmp_path: Path) -> None:
    """В dev профиле политика не проверяется (dev — не prod-контур)."""
    profiles = tmp_path / "profiles"
    profiles.mkdir(parents=True, exist_ok=True)
    base = yaml.safe_load((PROFILES_DIR / "base.yml").read_text(encoding="utf-8"))
    base.setdefault("app", {})["environment"] = "development"
    (profiles / "base.yml").write_text(
        yaml.safe_dump(base, allow_unicode=True), encoding="utf-8"
    )
    (profiles / "dev.yml").write_text(
        yaml.safe_dump({"features": {"dsl_capability_gate_enabled": False}}),
        encoding="utf-8",
    )

    violations = validate_profile_config("dev", profiles)
    codes = {violation.code for violation in violations}

    assert "feature_flag.dsl_capability_gate_disabled" not in codes
