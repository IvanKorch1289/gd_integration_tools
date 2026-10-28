"""Wave 13 Q1 — эффективный ``log.level`` в профилях окружения.

Контекст: ``config_profiles/base.yml`` задаёт ``log.level: "DEBUG"`` для всех
профилей. Профили ``prod``/``staging`` уровень не переопределяли → в проде
логи писались на DEBUG (значение уходит напрямую в ``root_logger.setLevel``).

Ожидание: в ``prod``/``staging`` уровень ``INFO``, в ``dev``/``dev_light`` —
``DEBUG`` (``dev`` наследует base, ``dev_light`` задаёт явно).
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

pytestmark = pytest.mark.unit

REPO_ROOT = Path(__file__).resolve().parents[4]
PROFILES_DIR = REPO_ROOT / "config_profiles"


def _load_yaml(path: Path) -> dict[str, Any]:
    """Читает YAML-файл профиля через ``yaml.safe_load``.

    Args:
        path: Путь к YAML-файлу.

    Returns:
        Разобранный mapping (пустой dict для пустого файла).
    """
    with open(path) as fh:
        data = yaml.safe_load(fh) or {}
    return data if isinstance(data, dict) else {}


def _merged_profile(profile_name: str) -> dict[str, Any]:
    """Сливает ``base.yml`` + ``{profile}.yml`` так же, как это делает прод-код.

    Args:
        profile_name: Имя профиля (``prod``/``staging``/``dev``/``dev_light``).

    Returns:
        Итоговый конфиг после ``_deep_merge`` из ``config_loader``.
    """
    from src.backend.core.config.config_loader import _deep_merge

    return _deep_merge(
        _load_yaml(PROFILES_DIR / "base.yml"),
        _load_yaml(PROFILES_DIR / f"{profile_name}.yml"),
    )


def _log_level(profile_name: str) -> str:
    """Возвращает эффективный ``log.level`` профиля после слияния YAML.

    Args:
        profile_name: Имя профиля.

    Returns:
        Значение ``log.level`` из объединённого конфига.
    """
    level = (_merged_profile(profile_name).get("log") or {}).get("level")
    assert isinstance(level, str), f"log.level отсутствует для профиля {profile_name}"
    return level


@pytest.mark.parametrize("profile_name", ["prod", "staging"])
def test_prod_like_profiles_use_info_level(profile_name: str) -> None:
    """prod/staging: эффективный ``log.level`` — ``INFO``, а не DEBUG из base."""
    assert _log_level(profile_name) == "INFO"


@pytest.mark.parametrize("profile_name", ["prod", "staging"])
def test_prod_like_profiles_declare_level_explicitly(profile_name: str) -> None:
    """prod/staging: уровень объявлен явно в overlay-файле профиля."""
    overlay = _load_yaml(PROFILES_DIR / f"{profile_name}.yml")
    assert (overlay.get("log") or {}).get("level") == "INFO"


@pytest.mark.parametrize("profile_name", ["dev", "dev_light"])
def test_dev_profiles_keep_debug_level(profile_name: str) -> None:
    """dev/dev_light: ``log.level`` остаётся ``DEBUG`` (dev наследует base)."""
    assert _log_level(profile_name) == "DEBUG"
