"""ЧАСТЬ B — ``manage.py validate-profile`` валидирует MERGED-конфиг (ADR-0375).

Дефект (до фикса): команда проверяла ТОЛЬКО overlay-файл профиля. Но
рантайм читает ``base.yml`` + overlay (``_deep_merge``), поэтому
инварианты, объявленные в ``base.yml``, оставались невидимыми для
валидатора — «зелёный» отчёт не означал «эффективный конфиг валиден».

Контракт:

* merged-конфиг (base + overlay) проходит ``ConfigValidator`` без
  CRITICAL для prod/staging;
* отчёт команды явно говорит, что проверен merged-конфиг;
* нарушение, пришедшее ИЗ ``base.yml`` (overlay чистый), всё равно
  ловится — overlay-only проверка больше не единственная.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml
from typer.testing import CliRunner

from manage import app
from src.backend.core.config.validator import ConfigSeverity
from src.backend.core.config.validator.profile_merge import (
    merge_profile_yaml,
    validate_profile_config,
)

pytestmark = pytest.mark.unit

REPO_ROOT = Path(__file__).resolve().parents[4]
PROFILES_DIR = REPO_ROOT / "config_profiles"

PROD_LIKE_PROFILES: tuple[str, ...] = ("prod", "staging")


@pytest.fixture
def runner() -> CliRunner:
    """Typer-runner для CLI-команд."""
    return CliRunner()


def _write_profiles(directory: Path, base: str, overlay: str) -> Path:
    """Создаёт временный каталог с base.yml + overlay профиля.

    Args:
        directory: Каталог ``config_profiles``.
        base: Содержимое ``base.yml``.
        overlay: Содержимое overlay-файла профиля.

    Returns:
        Путь к каталогу профилей.
    """
    directory.mkdir(parents=True, exist_ok=True)
    (directory / "base.yml").write_text(base, encoding="utf-8")
    (directory / "prod.yml").write_text(overlay, encoding="utf-8")
    return directory


def _prod_like_base_without_waf() -> str:
    """Prod-конфиг целиком в ``base.yml`` (без секции ``waf``).

    Нужно, чтобы синтетический профиль был ПОЛНЫМ (все обязательные поля
    присутствуют) и при этом содержал нарушение, которого нет в overlay.

    Returns:
        YAML-текст ``base.yml``.
    """
    base = yaml.safe_load((PROFILES_DIR / "base.yml").read_text()) or {}
    prod = yaml.safe_load((PROFILES_DIR / "prod.yml").read_text()) or {}
    merged = {**base, **{key: value for key, value in prod.items() if key != "waf"}}
    return yaml.safe_dump(merged, sort_keys=False, allow_unicode=True)


class TestMergedProfileHasNoCritical:
    """Merged-конфиг prod/staging проходит валидатор без CRITICAL."""

    @pytest.mark.parametrize("profile", PROD_LIKE_PROFILES)
    def test_no_critical_violations(self, profile: str) -> None:
        """Ни одного CRITICAL на merged-конфиге профиля."""
        violations = validate_profile_config(profile)
        critical = [
            violation.code
            for violation in violations
            if violation.severity == ConfigSeverity.CRITICAL
        ]
        assert critical == [], f"профиль {profile}: CRITICAL-нарушения: {critical}"

    @pytest.mark.parametrize("profile", PROD_LIKE_PROFILES)
    def test_merged_contains_base_values(self, profile: str) -> None:
        """Merged-конфиг содержит значения из ``base.yml`` (не только overlay)."""
        merged = merge_profile_yaml(profile)
        base = yaml.safe_load((PROFILES_DIR / "base.yml").read_text()) or {}
        assert merged["http"]["ssl_verify"] == base["http"]["ssl_verify"]
        assert (
            merged["graphql"]["enable_introspection"]
            == base["graphql"]["enable_introspection"]
        )


class TestManageCommandValidatesMerged:
    """CLI-команда валидирует merged-конфиг, а не только overlay."""

    @pytest.mark.parametrize("profile", PROD_LIKE_PROFILES)
    def test_command_exits_zero(self, runner: CliRunner, profile: str) -> None:
        """Для prod/staging команда завершается с кодом 0."""
        result = runner.invoke(app, ["validate-profile", profile])
        assert result.exit_code == 0, f"{profile}: {result.stdout} {result.stderr}"

    @pytest.mark.parametrize("profile", PROD_LIKE_PROFILES)
    def test_command_reports_merged_config(
        self, runner: CliRunner, profile: str
    ) -> None:
        """Отчёт явно сообщает о проверке merged-конфига."""
        result = runner.invoke(app, ["validate-profile", profile])
        combined = result.stdout + (result.stderr or "")
        assert "merged-конфиг" in combined, combined

    def test_base_violation_is_detected(self, tmp_path: Path) -> None:
        """Нарушение из ``base.yml`` ловится, даже если overlay чистый."""
        profiles = _write_profiles(
            tmp_path / "config_profiles",
            base=_prod_like_base_without_waf(),
            overlay="{}\n",
        )
        violations = validate_profile_config("prod", profiles)
        critical = [
            violation.code
            for violation in violations
            if violation.severity == ConfigSeverity.CRITICAL
        ]
        assert "waf.strict_required_in_prod" in critical, (
            "нарушение из base.yml должно ловиться merged-валидацией"
        )

    def test_overlay_only_check_would_have_passed(self, tmp_path: Path) -> None:
        """Overlay-only проверка прошла бы — merged-валидация ловит дефект."""
        profiles = _write_profiles(
            tmp_path / "config_profiles",
            base=_prod_like_base_without_waf(),
            overlay="{}\n",
        )
        overlay: dict[str, Any] = (
            yaml.safe_load((profiles / "prod.yml").read_text()) or {}
        )
        # Старая проверка смотрела только в overlay — секции waf там нет,
        # поэтому permissive-WAF в production был не виден.
        assert "waf" not in overlay
        violations = validate_profile_config("prod", profiles)
        assert any(
            violation.code == "waf.strict_required_in_prod" for violation in violations
        )

    def test_incomplete_profile_is_reported(self, tmp_path: Path) -> None:
        """Неполный профиль даёт Violation, а не ``AttributeError``."""
        profiles = _write_profiles(
            tmp_path / "config_profiles",
            base="app:\n  environment: production\n",
            overlay="{}\n",
        )
        violations = validate_profile_config("prod", profiles)
        assert any(violation.code == "profile.incomplete" for violation in violations)


class TestConstantsSectionValidated:
    """Секция ``constants`` валидируется merged-валидатором (ADR-0377).

    Дефект (до фикса): секция ``constants`` собиралась через
    ``model_construct`` (без валидации) — ``initial_delay: -5`` проходил
    ``manage.py validate-profile`` насквозь и ронял старт процесса
    (``ValidationError`` при создании ``ConstantsSettings``).
    """

    def test_negative_initial_delay_is_critical(self, tmp_path: Path) -> None:
        """Отрицательный ``initial_delay`` — CRITICAL-нарушение."""
        profiles = _write_profiles(
            tmp_path / "config_profiles",
            base=_prod_like_base_without_waf(),
            overlay="constants:\n  initial_delay: -5\n",
        )
        violations = validate_profile_config("prod", profiles)
        critical = [
            violation.code
            for violation in violations
            if violation.severity == ConfigSeverity.CRITICAL
        ]
        assert "constants.invalid" in critical

    def test_zero_recovery_seconds_is_critical(self, tmp_path: Path) -> None:
        """Нулевой ``default_cb_recovery_seconds`` — CRITICAL (gt=0)."""
        profiles = _write_profiles(
            tmp_path / "config_profiles",
            base=_prod_like_base_without_waf(),
            overlay="constants:\n  default_cb_recovery_seconds: 0\n",
        )
        violations = validate_profile_config("prod", profiles)
        assert any(violation.code == "constants.invalid" for violation in violations), (
            "нарушение ограничения constants должно ловиться"
        )

    def test_valid_constants_produce_no_violation(self, tmp_path: Path) -> None:
        """Валидные значения constants не дают нарушений."""
        profiles = _write_profiles(
            tmp_path / "config_profiles",
            base=_prod_like_base_without_waf(),
            overlay="constants:\n  initial_delay: 10\n  retry_delay: 5\n",
        )
        violations = validate_profile_config("prod", profiles)
        assert not [
            violation
            for violation in violations
            if violation.code == "constants.invalid"
        ]

    def test_validation_does_not_mutate_global_constants(self, tmp_path: Path) -> None:
        """Валидация не применяет YAML-значения к синглтону ``consts``."""
        from src.backend.core.config.constants import consts

        before = consts.INITIAL_DELAY
        profiles = _write_profiles(
            tmp_path / "config_profiles",
            base=_prod_like_base_without_waf(),
            overlay="constants:\n  initial_delay: 42\n",
        )
        validate_profile_config("prod", profiles)
        assert consts.INITIAL_DELAY == before

    @pytest.mark.parametrize("profile", PROD_LIKE_PROFILES)
    def test_repo_profiles_have_valid_constants(self, profile: str) -> None:
        """Секция ``constants`` в реальных профилях валидна."""
        violations = validate_profile_config(profile)
        assert not [
            violation
            for violation in violations
            if violation.code == "constants.invalid"
        ]
