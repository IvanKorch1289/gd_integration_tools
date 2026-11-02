"""ADR-0419: prod-профиль — ``waf.clamav_fail_open: false``.

Дефект: в ``config_profiles/base.yml`` стояло ``waf.clamav_fail_open: true``,
а prod-профиль это не переопределял → ``manage.py validate-profile prod``
давал WARNING ``waf.clamav_fail_open_in_prod``: при недоступном clamd
исходящие запросы проходили без AV-сканирования.

Фикс: prod переопределяет ``clamav_fail_open: false`` (fail-closed).

Осознанное решение по «неразрешимому конфликту»: конфликта нет.
* ``waf.clamav_enabled: true`` + ``clamav_host: "clamd"`` (service-DNS,
  ``deploy/k8s/service.yaml``) — в prod clamd развёрнут как sidecar;
* если платформа не разворачивает clamd — в prod следует поставить
  ``waf.clamav_enabled: false`` (сканер не подключается, ``fail_open``
  нерелевантен) — это явный выбор, а не молчаливый fail-open.
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

CLAMAV_WARNING_CODE = "waf.clamav_fail_open_in_prod"


def _merged_prod() -> dict[str, Any]:
    """Слить ``base.yml`` + ``prod.yml`` (как это делает валидатор)."""
    base = yaml.safe_load((PROFILES_DIR / "base.yml").read_text(encoding="utf-8")) or {}
    prod = yaml.safe_load((PROFILES_DIR / "prod.yml").read_text(encoding="utf-8")) or {}
    merged = dict(base)
    for section, values in prod.items():
        if isinstance(values, dict) and isinstance(merged.get(section), dict):
            merged[section] = {**merged[section], **values}
        else:
            merged[section] = values
    return merged


def test_prod_profile_disables_clamav_fail_open() -> None:
    """В prod ``waf.clamav_fail_open`` — строго false."""
    waf = _merged_prod().get("waf") or {}

    assert waf.get("clamav_fail_open") is False


def test_prod_profile_has_no_clamav_fail_open_warning() -> None:
    """``validate-profile prod`` — без WARNING ``waf.clamav_fail_open_in_prod``."""
    violations = validate_profile_config("prod")

    codes = [
        violation.code
        for violation in violations
        if violation.severity == ConfigSeverity.WARNING
    ]

    assert CLAMAV_WARNING_CODE not in codes


def test_base_profile_keeps_dev_default() -> None:
    """base.yml остаётся fail-open (dev без clamd sidecar'а)."""
    base = yaml.safe_load((PROFILES_DIR / "base.yml").read_text(encoding="utf-8")) or {}

    assert (base.get("waf") or {}).get("clamav_fail_open") is True


def test_clamav_disabled_makes_fail_open_irrelevant(tmp_path: Path) -> None:
    """Явный escape-hatch: ``clamav_enabled: false`` — сканер не подключается.

    В этом режиме ``fail_open`` не влияет ни на что (сканера нет), поэтому
    WARNING не выдаётся — конфликта «fail_closed без clamd» не возникает.
    """
    profiles = tmp_path / "config_profiles"
    profiles.mkdir(parents=True, exist_ok=True)
    for name in ("base.yml", "prod.yml"):
        (profiles / name).write_text(
            (PROFILES_DIR / name).read_text(encoding="utf-8"), encoding="utf-8"
        )
    prod_path = profiles / "prod.yml"
    prod_data = yaml.safe_load(prod_path.read_text(encoding="utf-8")) or {}
    prod_data.setdefault("waf", {})["clamav_enabled"] = False
    prod_data["waf"]["clamav_fail_open"] = True
    prod_path.write_text(
        yaml.safe_dump(prod_data, sort_keys=False, allow_unicode=True), encoding="utf-8"
    )

    violations = validate_profile_config("prod", profiles)

    codes = [
        violation.code
        for violation in violations
        if violation.severity == ConfigSeverity.WARNING
    ]
    assert CLAMAV_WARNING_CODE not in codes
