"""Sprint 14 W1 — CLI-проверка матрицы совместимости плагинов.

Назначение:
    Сканирует ``extensions/`` (или указанный каталог), парсит каждый
    ``plugin.toml`` через :class:`PluginManifest`, запускает
    :func:`check_compatibility` и завершает с ``exit 1`` при наличии
    нарушений.

Использование:
    python -m tools.checks.check_compat
    python -m tools.checks.check_compat --plugins-dir extensions/ --core-version 0.2.5

Аргументы:
    --plugins-dir  Каталог с плагинами (default: extensions/).
    --core-version Версия ядра для проверки ``incompatible_core_versions``.
                   Если не задана — берётся из переменной окружения
                   ``GDIT_CORE_VERSION`` или фолбэк ``"0.0.0"``.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from src.backend.core.plugin_runtime.compat_checker import check_compatibility
from src.backend.services.plugins.manifest_toml import (
    PluginManifestError,
    PluginManifest,
    load_plugin_manifest,
)

_OK = "[OK]"
_ERR = "[ERROR]"


def _collect_manifests(plugins_dir: Path) -> list[PluginManifest]:
    """Прочитать все валидные ``plugin.toml`` из каталога."""
    manifests: list[PluginManifest] = []
    for child in sorted(plugins_dir.iterdir()):
        manifest_path = child / "plugin.toml"
        if not manifest_path.is_file():
            continue
        try:
            manifests.append(load_plugin_manifest(manifest_path))
        except PluginManifestError as exc:
            print(f"{_ERR} {manifest_path}: {exc}", file=sys.stderr)
    return manifests


def main(argv: list[str] | None = None) -> int:
    """CLI entrypoint."""
    parser = argparse.ArgumentParser(
        description="Проверка матрицы совместимости плагинов (S14 W1)."
    )
    parser.add_argument(
        "--plugins-dir",
        type=Path,
        default=Path("extensions"),
        help="Корневой каталог с плагинами.",
    )
    parser.add_argument(
        "--core-version",
        default=os.environ.get("GDIT_CORE_VERSION", "0.0.0"),
        help="Версия ядра для проверки incompatible_core_versions.",
    )
    args = parser.parse_args(argv)

    plugins_dir: Path = args.plugins_dir
    if not plugins_dir.is_dir():
        print(f"{_OK} caталог {plugins_dir} отсутствует — нечего проверять.")
        return 0

    manifests = _collect_manifests(plugins_dir)
    if not manifests:
        print(f"{_OK} в {plugins_dir} нет валидных манифестов.")
        return 0

    violations = check_compatibility(manifests, core_version=args.core_version)
    if not violations:
        print(f"{_OK} compatibility matrix: {len(manifests)} плагин(ов) совместимы.")
        return 0

    for v in violations:
        print(
            f"{_ERR} {v.plugin} ↔ {v.conflicting_plugin} ({v.kind}): {v.reason}",
            file=sys.stderr,
        )
    print(f"{_ERR} найдено {len(violations)} нарушений.", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
