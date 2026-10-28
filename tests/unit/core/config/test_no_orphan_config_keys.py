"""Wave 13 Q17 — в ``config_profiles`` нет мёртвой конфигурации (orphan-ключей).

Контекст: ``config_profiles/base.yml`` содержал 10 ключей, которых нет ни в
одной модели ``src/backend/core/config``. YAML-источник
(``YamlConfigSettingsLoader._filter_data``) фильтрует секцию по
``model_fields``, поэтому такие ключи молча игнорировались: значения
выглядели как hardening-требования (``bind_host: 127.0.0.1``), но код их
никогда не видел — иллюзия настраиваемости (ADR-0351).

Ожидание:
    * ни одна top-level секция профиля не является «призраком» (нет класса с
      таким ``yaml_group``);
    * внутри каждой секции нет ключа без соответствующего поля модели;
    * конкретные мёртвые пути (список ниже) отсутствуют в YAML-файлах профилей;
    * перенесённые в реальные секции значения сохранены (queue/mcp/app).

Логика аудита переиспользуется из ``tools/config_audit.py`` — без дублирования
реализации.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

from tools import config_audit

pytestmark = pytest.mark.unit

REPO_ROOT = Path(__file__).resolve().parents[4]
PROFILES_DIR = REPO_ROOT / "config_profiles"

# Мёртвые пути (dot-path) из волны 13 Q17: ключи, которые не читает ни одна
# модель конфигурации. Путь через точку — вложенность YAML, без точки —
# top-level ключ.
DEAD_KEY_PATHS: tuple[str, ...] = (
    "http3",  # секция-призрак: HTTP/3 настраивается в группе app
    "queue_consumer_max_prefetch",  # реальное поле — queue.consumer_max_prefetch
    "mcp.http_path",  # в модели поле называется bind_path
    "mcp.sse_enabled",
    "mcp.stdio_enabled",
    "mcp.bind_host",
    "mcp.bind_port",
    "mqtt.require_client_auth",
    "mqtt.bind_host",
    "mqtt.bind_port",
)


class _Missing:
    """Сентинел «ключ отсутствует» (с читаемым repr в сообщениях pytest)."""

    def __repr__(self) -> str:
        """Возвращает текстовое представление сентинела.

        Returns:
            Строка ``<missing>``.
        """
        return "<missing>"


_MISSING = _Missing()


def _load_yaml(path: Path) -> dict[str, Any]:
    """Читает YAML-файл профиля.

    Args:
        path: Путь к YAML-файлу.

    Returns:
        Разобранный mapping (пустой dict для пустого файла).
    """
    with open(path) as fh:
        data = yaml.safe_load(fh) or {}
    return data if isinstance(data, dict) else {}


def _resolve(data: dict[str, Any], dotted: str) -> Any:
    """Извлекает значение по dot-path из вложенного mapping.

    Args:
        data: Корневой mapping.
        dotted: Путь через точку (``mcp.bind_path``) либо top-level ключ.

    Returns:
        Значение по пути либо ``_MISSING``, если путь отсутствует.
    """
    current: Any = data
    for part in dotted.split("."):
        if not isinstance(current, dict) or part not in current:
            return _MISSING
        current = current[part]
    return current


def _merged_profile(profile: str) -> dict[str, Any]:
    """Сливает ``base.yml`` + ``{profile}.yml`` (как в ``config_loader``).

    Args:
        profile: Имя профиля окружения.

    Returns:
        Итоговый конфиг после слияния.
    """
    return config_audit._load_profile_yaml(profile)


@pytest.fixture(scope="module")
def settings_classes() -> dict[str, tuple[Any, dict[str, Any], str]]:
    """Карта ``yaml_group -> (spec, fields, env_prefix)`` из моделей конфигурации.

    Returns:
        Соответствие yaml-групп полям моделей ``src/backend/core/config``.
    """
    registry = config_audit._parse_config_classes(config_audit.CONFIG_DIR)
    return config_audit._settings_classes(registry)


@pytest.mark.parametrize("profile", config_audit.PROFILES)
def test_profile_has_no_orphan_groups(
    profile: str, settings_classes: dict[str, tuple[Any, dict[str, Any], str]]
) -> None:
    """В профиле нет top-level секций без соответствующего класса настроек."""
    _, orphan_groups = config_audit._audit_profile(profile, settings_classes, set())
    assert orphan_groups == [], (
        f"профиль {profile}: секции без модели (yaml_group): {orphan_groups}"
    )


@pytest.mark.parametrize("profile", config_audit.PROFILES)
def test_profile_has_no_orphan_keys(
    profile: str, settings_classes: dict[str, tuple[Any, dict[str, Any], str]]
) -> None:
    """В профиле нет ключей внутри секций, которым нет полей в модели."""
    reports, _ = config_audit._audit_profile(profile, settings_classes, set())
    orphans = {r.group: r.orphan_keys for r in reports if r.orphan_keys}
    assert orphans == {}, f"профиль {profile}: orphan-ключи: {orphans}"


@pytest.mark.parametrize(
    "profile_path", sorted(PROFILES_DIR.glob("*.yml")), ids=lambda path: path.name
)
def test_dead_config_keys_absent_in_profile_files(profile_path: Path) -> None:
    """Мёртвые ключи волны 13 Q17 отсутствуют в YAML-файлах профилей."""
    data = _load_yaml(profile_path)
    found = [path for path in DEAD_KEY_PATHS if _resolve(data, path) is not _MISSING]
    assert not found, f"{profile_path.name}: мёртвые ключи конфигурации: {found}"


@pytest.mark.parametrize("profile", config_audit.PROFILES)
def test_queue_prefetch_declared_in_queue_group(profile: str) -> None:
    """``queue_consumer_max_prefetch`` перенесён в ``queue.consumer_max_prefetch``."""
    value = _resolve(_merged_profile(profile), "queue.consumer_max_prefetch")
    assert value == 10, f"профиль {profile}: queue.consumer_max_prefetch={value!r}"


@pytest.mark.parametrize("profile", config_audit.PROFILES)
def test_mcp_bind_path_declared(profile: str) -> None:
    """MCP-путь объявлен полем модели ``mcp.bind_path``."""
    value = _resolve(_merged_profile(profile), "mcp.bind_path")
    assert value == "/mcp", f"профиль {profile}: mcp.bind_path={value!r}"


@pytest.mark.parametrize("profile", config_audit.PROFILES)
def test_http3_settings_declared_in_app_group(profile: str) -> None:
    """HTTP/3 настраивается в группе ``app`` (реальные поля модели)."""
    merged = _merged_profile(profile)
    assert _resolve(merged, "app.http3_enabled") is False
    assert _resolve(merged, "app.http3_port") == 8443


def test_prod_compression_settings_declared_in_app_group() -> None:
    """Prod-настройки сжатия живут в ``app`` (их читает compression-middleware)."""
    merged = _merged_profile("prod")
    assert _resolve(merged, "app.compression_brotli") is True
    assert _resolve(merged, "app.gzip_minimum_size") == 512
    assert _resolve(merged, "app.gzip_compresslevel") == 6
