"""RPASettings — конфиг не должен врать (ADR-0370, cycle 172).

D3 (решение владельца): 13 мёртвых полей ``RPASettings`` удалены —
ни одно из них не читается в рантайме, но они создавали ложное
впечатление настраиваемости (``extra="forbid"`` + живой env → падение
старта). Проверка ниже фиксирует инвариант: в модели остаются только
поля, которые реально читает ``services/rpa/browser_pool.py``.

Дополнительно проверяется, что секция ``rpa:`` в ``config_profiles/base.yml``
содержит ровно живые поля (ADR-0362: ключ в YAML без поля в модели —
orphan, блокирующий гейт ``tools/config_audit.py --scope orphans``).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from src.backend.core.config.services.rpa import RPASettings

#: Поля, которые читает ``services/rpa/browser_pool.py``.
LIVE_FIELDS: tuple[str, ...] = (
    "browser_pool_size",
    "browser_headless",
    "browser_launch_max_retries",
    "browser_launch_retry_base_seconds",
)

#: Мёртвые поля (ADR-0370, решение D3): ни одного чтения в ``src/``.
DEAD_FIELDS: tuple[str, ...] = (
    "desktop_base_url",
    "desktop_api_key",
    "desktop_timeout",
    "desktop_ttl_seconds",
    "desktop_max_sessions",
    "desktop_cb_failure_threshold",
    "desktop_cb_recovery_seconds",
    "desktop_retry_max_attempts",
    "browser_kind",
    "browser_viewport_width",
    "browser_viewport_height",
    "ocr_enabled",
    "ocr_default_lang",
)

_BASE_YML = Path(__file__).resolve().parents[4] / "config_profiles" / "base.yml"


def _base_rpa_section() -> dict[str, Any]:
    """Секция ``rpa:`` из ``config_profiles/base.yml``."""
    raw = yaml.safe_load(_BASE_YML.read_text(encoding="utf-8")) or {}
    section = raw.get("rpa")
    assert isinstance(section, dict), "секция rpa: отсутствует в base.yml"
    return section


def test_model_has_no_dead_fields() -> None:
    """Мёртвых полей в RPASettings быть не должно (решение D3)."""
    dead_present = sorted(set(DEAD_FIELDS) & set(RPASettings.model_fields))
    assert not dead_present, f"мёртвые поля вернулись в RPASettings: {dead_present}"


def test_model_keeps_only_live_fields() -> None:
    """В модели ровно живые поля — ничего лишнего, ничего не потеряно."""
    assert tuple(sorted(RPASettings.model_fields)) == tuple(sorted(LIVE_FIELDS))


def test_base_profile_rpa_section_matches_live_fields() -> None:
    """Секция ``rpa:`` в base.yml совпадает с живыми полями модели."""
    assert tuple(sorted(_base_rpa_section())) == tuple(sorted(LIVE_FIELDS))


def test_base_profile_rpa_section_has_no_orphan_keys() -> None:
    """Ни один ключ YAML-секции не ссылается на удалённое поле."""
    orphans = sorted(set(_base_rpa_section()) & set(DEAD_FIELDS))
    assert not orphans, f"в base.yml остались мёртвые ключи rpa: {orphans}"


def test_env_prefix_kept_for_live_fields() -> None:
    """env-префикс ``RPA_`` сохранён (backward-compat для живых полей)."""
    assert RPASettings.model_config.get("env_prefix") == "RPA_"
    assert RPASettings.model_config.get("extra") == "forbid"
