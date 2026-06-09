"""Sprint 14 K5 W2 — управление версиями и rollback плагинов.

Назначение:
    Сервис ``PluginVersionService`` инкапсулирует:

    * ``list_versions(plugin)`` — найти все локально установленные версии
      плагина (по конвенции ``extensions/<plugin>.<version>/`` или
      git-tagged backups);
    * ``diff(plugin, from_ver, to_ver)`` — делегация в
      :class:`MigrationDiffer` для structured-diff;
    * ``rollback(plugin, to_version)`` — atomic symlink-switch
      ``extensions/<plugin>`` → ``extensions/<plugin>.<version>`` + hot-swap
      reload через :func:`hot_swap`.

    Health-check после rollback: smoke-check от loader (если у него есть
    метод ``smoke_check``; fallback — ``discover_and_load`` + проверить
    ``status == "loaded"``).

Использование:
    service = PluginVersionService(loader=loader, extensions_dir=Path("extensions"))
    versions = service.list_versions("credit_pipeline")
    diff = service.diff("credit_pipeline", from_ver="1.0.0", to_ver="2.0.0")
    result = await service.rollback("credit_pipeline", to_version="1.0.0")

Зависимости:
    - PluginLoaderV11 (для discovery + smoke-check);
    - hot_swap (для атомарной reload);
    - plugin_migration_diff (для diff endpoint).
"""

from __future__ import annotations

import tomllib
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

from src.backend.core.logging import get_logger
from tools.plugin_migration_diff import MigrationDiffer

if TYPE_CHECKING:
    from src.backend.core.plugin_runtime.hot_swap import (
        HotSwapResult,
        PluginLoaderProtocol,
    )

__all__ = (
    "InstalledVersion",
    "PluginVersionError",
    "PluginVersionService",
    "RollbackResult",
)

_logger = get_logger("services.plugins.versioning")


class PluginVersionError(RuntimeError):
    """Базовая ошибка versioning-операций."""


@dataclass(slots=True, frozen=True)
class InstalledVersion:
    """Описание одной локально установленной версии плагина."""

    plugin: str
    version: str
    path: Path
    is_active: bool

    def to_dict(self) -> dict[str, Any]:
        return {**asdict(self), "path": str(self.path)}


@dataclass(slots=True, frozen=True)
class RollbackResult:
    """Итог rollback-операции."""

    plugin: str
    from_version: str
    to_version: str
    status: str  # "rolled_back" | "noop" | "failed"
    reason: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class PluginVersionService:
    """Управление версиями и rollback через symlink-switching.

    Конвенция backup-каталогов: ``extensions/<plugin>.<version>/`` — это
    «архивные» снимки конкретных версий. Активный каталог
    ``extensions/<plugin>/`` либо symlink на один из снимков, либо
    обычный каталог (deploy через wheel).
    """

    def __init__(self, *, loader: PluginLoaderProtocol, extensions_dir: Path) -> None:
        self._loader = loader
        self._extensions_dir = extensions_dir

    def list_versions(self, plugin: str) -> list[InstalledVersion]:
        """Найти все локальные версии плагина.

        Сканирует:
        * Активный каталог ``extensions/<plugin>/`` (если есть);
        * Backup-каталоги ``extensions/<plugin>.*``.
        """
        if not self._extensions_dir.is_dir():
            return []
        active_path = self._extensions_dir / plugin
        active_version = self._read_version(active_path)

        installed: list[InstalledVersion] = []
        if active_version is not None:
            installed.append(
                InstalledVersion(
                    plugin=plugin,
                    version=active_version,
                    path=active_path,
                    is_active=True,
                )
            )

        prefix = f"{plugin}."
        for child in sorted(self._extensions_dir.iterdir()):
            if not child.is_dir() or not child.name.startswith(prefix):
                continue
            version = child.name[len(prefix) :]
            installed.append(
                InstalledVersion(
                    plugin=plugin, version=version, path=child, is_active=False
                )
            )
        return installed

    def diff(self, plugin: str, from_version: str, to_version: str) -> dict[str, Any]:
        """Структурированный diff двух версий (использует MigrationDiffer).

        Версии должны существовать локально (см. :meth:`list_versions`).
        """
        old_path = self._resolve_version_path(plugin, from_version)
        new_path = self._resolve_version_path(plugin, to_version)
        old_toml = _load_toml(old_path / "plugin.toml")
        new_toml = _load_toml(new_path / "plugin.toml")

        diff = MigrationDiffer().diff(plugin, old_toml, new_toml)
        return {
            "plugin": diff.plugin,
            "from_version": diff.from_version,
            "to_version": diff.to_version,
            "payload": diff.payload,
        }

    async def rollback(self, plugin: str, *, to_version: str) -> RollbackResult:
        """Atomic-rollback: переключить symlink + hot-swap reload.

        Шаги:

        1. Найти target-снимок ``extensions/<plugin>.<to_version>``.
        2. Если активный каталог уже эта версия — noop.
        3. Архивировать текущую активную версию в
           ``extensions/<plugin>.<current_version>`` (если её ещё нет).
        4. Удалить symlink/каталог ``extensions/<plugin>`` и создать
           symlink на target-снимок.
        5. Запустить hot-swap (reload через
           :func:`core.plugin_runtime.hot_swap.hot_swap`).
        6. Smoke-check через loader — статус должен быть ``"loaded"``.
        """
        active_path = self._extensions_dir / plugin
        target_path = self._extensions_dir / f"{plugin}.{to_version}"
        if not target_path.is_dir():
            raise PluginVersionError(f"version snapshot not found: {target_path}")

        current_version = self._read_version(active_path) or "?"
        if current_version == to_version:
            return RollbackResult(
                plugin=plugin,
                from_version=current_version,
                to_version=to_version,
                status="noop",
                reason="already active",
            )

        try:
            self._archive_current(plugin, active_path, current_version)
            self._switch_symlink(active_path, target_path)
        except OSError as exc:
            return RollbackResult(
                plugin=plugin,
                from_version=current_version,
                to_version=to_version,
                status="failed",
                reason=f"symlink_switch_failed: {exc}",
            )

        from src.backend.core.plugin_runtime.hot_swap import HotSwapError, hot_swap

        try:
            hot_swap_result: HotSwapResult = await hot_swap(plugin, self._loader)
        except HotSwapError as exc:
            return RollbackResult(
                plugin=plugin,
                from_version=current_version,
                to_version=to_version,
                status="failed",
                reason=f"hot_swap_failed: {exc.reason}",
            )

        if hot_swap_result.status != "reloaded":
            return RollbackResult(
                plugin=plugin,
                from_version=current_version,
                to_version=to_version,
                status="failed",
                reason=hot_swap_result.reason or "smoke_check_failed",
            )

        return RollbackResult(
            plugin=plugin,
            from_version=current_version,
            to_version=to_version,
            status="rolled_back",
        )

    # ── internals ────────────────────────────────────────────────────────

    def _resolve_version_path(self, plugin: str, version: str) -> Path:
        """Найти путь к конкретной версии (active или backup)."""
        active = self._extensions_dir / plugin
        if self._read_version(active) == version:
            return active
        backup = self._extensions_dir / f"{plugin}.{version}"
        if backup.is_dir():
            return backup
        raise PluginVersionError(f"version {version!r} not found for {plugin!r}")

    @staticmethod
    def _read_version(path: Path) -> str | None:
        manifest = path / "plugin.toml"
        if not manifest.is_file():
            return None
        try:
            data = _load_toml(manifest)
            return str(data.get("version")) if data.get("version") else None
        except Exception as _:
            return None

    def _archive_current(
        self, plugin: str, active_path: Path, current_version: str
    ) -> None:
        """Если active-каталог не symlink — копируем его в archive."""
        if not active_path.is_dir() or current_version == "?":
            return
        archive_path = self._extensions_dir / f"{plugin}.{current_version}"
        if archive_path.exists():
            return  # уже архивирован
        if active_path.is_symlink():
            return  # активная версия уже symlink — архивировать не нужно
        # Делаем shallow-rename — это даёт atomic swap на одной FS.
        try:
            active_path.rename(archive_path)
            _logger.info(
                "Archived current %s@%s → %s", plugin, current_version, archive_path
            )
        except OSError as exc:
            _logger.warning(
                "Failed to archive current %s@%s: %s", plugin, current_version, exc
            )

    @staticmethod
    def _switch_symlink(active_path: Path, target_path: Path) -> None:
        """Удалить старый symlink/каталог и создать новый."""
        if active_path.exists() or active_path.is_symlink():
            if active_path.is_symlink() or active_path.is_file():
                active_path.unlink()
            else:
                # Каталог не должен оставаться — но мы его уже архивировали
                # в _archive_current; если по какой-то причине остался —
                # ничего не делаем, fallback на ошибку.
                raise OSError(f"cannot remove non-symlink active dir: {active_path}")
        active_path.symlink_to(target_path.resolve(), target_is_directory=True)


def _load_toml(path: Path) -> dict[str, Any]:
    """Прочитать TOML-файл (raises FileNotFoundError если нет)."""
    with path.open("rb") as fh:
        return tomllib.load(fh)
