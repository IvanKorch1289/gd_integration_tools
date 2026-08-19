"""Cycle-15 (D-AUDIT-1502): read-only discovery of plugin ORM models.

Назначение:
    :func:`load_plugin_manifests_for_migrations` сканирует ``extensions/``,
    парсит каждый ``plugin.toml`` через :func:`load_plugin_manifest` и
    возвращает список :class:`PluginManifest` без вызова lifecycle /
    import entry_class. Используется :mod:`migrations.env` для auto-import
    SQLAlchemy ORM-модулей, объявленных в ``manifest.models_module``.

Почему отдельный модуль (а не :class:`PluginLoader.discover_and_load`):
    * ``PluginLoader.discover_and_load`` асинхронный и создаёт экземпляры
      :class:`BasePlugin` через ``importlib.import_module(entry_class)`` —
      дорого и нежелательно в Alembic-окружении, где рантайм может быть
      в partial-init состоянии.
    * Здесь нужен минимальный sync API: walk каталога → parse TOML → collect
      :attr:`PluginManifest.models_module`. Без capability-gate, без
      lifecycle-хуков, без instantiation.
    * Parse-failures (битый TOML, schema violation) логируются и пропускаются
      — partial discovery для миграций безопаснее, чем hard-fail.

Backward compat:
    Плагины без ``models_module = [...]`` в манифесте участвуют в discovery,
    но не вносят путей в итоговый список — это эквивалентно
    pre-cycle-15 hardcoded импортам для core_entities/* (которые мы
    перенесём в plugin.toml в этом же цикле).
"""

from __future__ import annotations

from pathlib import Path
from typing import NamedTuple

from src.backend.core.logging import get_logger
from src.backend.core.plugin_runtime.manifest_toml import (
    PluginManifest,
    PluginManifestError,
    load_plugin_manifest,
)

__all__ = ("ManifestWithPath", "load_plugin_manifests_for_migrations")

_logger = get_logger("services.plugins.loader.models_discovery")


class ManifestWithPath(NamedTuple):
    """Пара (manifest, path) для downstream-обработки (например, env.py)."""

    manifest: PluginManifest
    manifest_path: Path


def load_plugin_manifests_for_migrations(
    extensions_dir: Path,
) -> list[ManifestWithPath]:
    """Сканировать ``extensions_dir`` и вернуть валидные manifest-объекты.

    Args:
        extensions_dir: Путь к каталогу ``extensions/`` (или test-fixture
            с in-tree плагинами).

    Returns:
        Список :class:`ManifestWithPath` в discovery-порядке (sorted по
        имени каталога для детерминизма). Parse-failures логируются
        как warning и пропускаются — env.py получит partial список
        и продолжит работу.

    Note:
        Функция sync (не async) — Alembic env.py выполняется под
        ``asyncio.run`` / sync context, async-IO здесь излишен.
        Парсинг одного TOML-файла — disk-bound операция; обычно
        5-15 плагинов × ~1 ms = 5-15 ms total. Допустимо для Alembic.

    """
    if not extensions_dir.is_dir():
        _logger.info(
            "Extensions dir %s not found — no plugin models discovered", extensions_dir
        )
        return []

    results: list[ManifestWithPath] = []
    for child in sorted(extensions_dir.iterdir()):
        manifest_path = child / "plugin.toml"
        if not manifest_path.is_file():
            continue
        try:
            manifest = load_plugin_manifest(manifest_path)
        except PluginManifestError as exc:
            _logger.warning(
                "Skipping plugin manifest at %s for migrations: %s", manifest_path, exc
            )
            continue
        results.append(ManifestWithPath(manifest=manifest, manifest_path=manifest_path))

    _logger.info(
        "Discovered %d plugin manifests for migrations (extensions_dir=%s)",
        len(results),
        extensions_dir,
    )
    return results
