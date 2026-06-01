"""Wave R1.2.b — конвертация ``plugin.yaml`` (Wave 4.4) → ``plugin.toml`` (V11).

Скрипт читает legacy ``plugins/<name>/plugin.yaml`` и пишет рядом
``plugin.toml`` в формате ADR-042. Поля, отсутствующие в legacy
(``requires_core``, ``capabilities``, ``tenant_aware``,
``provides.{sources,sinks,schemas}``), вставляются как placeholder'ы с
комментариями для ручного дозаполнения.

Запуск::

    uv run python tools/migrate_plugin_manifest.py plugins/example_plugin
    uv run python tools/migrate_plugin_manifest.py plugins/* --dry-run

Опции:

* ``--dry-run`` — печатает результат, не пишет файл.
* ``--core-spec`` — значение ``requires_core`` (по умолчанию ``">=0.2,<0.3"``).
* ``--overwrite`` — перезаписать существующий ``plugin.toml``.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Iterable
from pathlib import Path

import yaml

__all__ = ("main", "migrate_one", "render_toml")


def render_toml(
    *,
    name: str,
    version: str,
    requires_core: str,
    entry_class: str,
    description: str | None,
    actions: tuple[str, ...],
    repositories: tuple[str, ...],
    processors: tuple[str, ...],
    config: dict[str, object],
) -> str:
    """Сгенерировать TOML-документ V11-манифеста."""
    lines: list[str] = [
        f'name = "{name}"',
        f'version = "{version}"',
        f'requires_core = "{requires_core}"',
        f'entry_class = "{entry_class}"',
        "tenant_aware = false  # TODO Wave R1: подтвердить multi-tenancy semantics",
    ]
    if description:
        lines.append(f'description = "{description}"')
    lines.extend(
        [
            "",
            "# TODO Wave R1: задекларировать capabilities для capability-gate.",
            "# [[capabilities]]",
            '# name = "db.read"',
            '# scope = "<dsn-alias>"',
        ]
    )
    if actions or repositories or processors:
        lines.append("")
        lines.append("[provides]")
        if actions:
            joined = ", ".join(f'"{a}"' for a in actions)
            lines.append(f"actions = [{joined}]")
        if repositories:
            joined = ", ".join(f'"{r}"' for r in repositories)
            lines.append(f"repositories = [{joined}]")
        if processors:
            joined = ", ".join(f'"{p}"' for p in processors)
            lines.append(f"processors = [{joined}]")
    if config:
        lines.append("")
        lines.append("[config]")
        for key, value in config.items():
            lines.append(f"{key} = {_render_toml_value(value)}")
    return "\n".join(lines) + "\n"


def _render_toml_value(value: object) -> str:
    """Простейший renderer для int/float/bool/str/list."""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, str):
        return f'"{value}"'
    if isinstance(value, list):
        joined = ", ".join(_render_toml_value(v) for v in value)
        return f"[{joined}]"
    raise TypeError(
        f"Unsupported config value type for TOML migration: {type(value).__name__}"
    )


def migrate_one(
    plugin_dir: Path, *, core_spec: str, overwrite: bool, dry_run: bool
) -> tuple[Path, str]:
    """Сконвертировать один ``plugin.yaml`` → ``plugin.toml``.

    Returns:
        Кортеж ``(target_path, rendered_toml)``.

    Raises:
        FileNotFoundError: Нет ``plugin.yaml`` в каталоге.
        FileExistsError: ``plugin.toml`` уже существует и не задан
            ``overwrite``.
    """
    yaml_path = plugin_dir / "plugin.yaml"
    if not yaml_path.is_file():
        raise FileNotFoundError(f"Missing legacy manifest: {yaml_path}")
    raw = yaml.safe_load(yaml_path.read_text(encoding="utf-8")) or {}
    if not isinstance(raw, dict):
        raise TypeError(f"plugin.yaml must be a mapping in {yaml_path}")

    name = str(raw.get("name", plugin_dir.name))
    version = str(raw.get("version", "0.0.0"))
    entry_class = str(raw.get("entry_class") or f"{name}.plugin.Plugin")
    actions = tuple(str(x) for x in raw.get("actions") or ())
    repositories = tuple(str(x) for x in raw.get("repositories") or ())
    processors = tuple(str(x) for x in raw.get("processors") or ())
    config = raw.get("config") or {}
    if not isinstance(config, dict):
        raise TypeError(
            f"plugin.yaml::config must be a mapping in {yaml_path}, got "
            f"{type(config).__name__}"
        )

    rendered = render_toml(
        name=name,
        version=version,
        requires_core=core_spec,
        entry_class=entry_class,
        description=raw.get("description"),
        actions=actions,
        repositories=repositories,
        processors=processors,
        config=config,
    )

    target = plugin_dir / "plugin.toml"
    if target.exists() and not overwrite:
        raise FileExistsError(f"{target} exists; pass --overwrite to replace")
    if not dry_run:
        target.write_text(rendered, encoding="utf-8")
    return target, rendered


def main(argv: Iterable[str] | None = None) -> int:
    """CLI entry point."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "plugin_dirs", nargs="+", type=Path, help="Каталоги плагинов с plugin.yaml."
    )
    parser.add_argument(
        "--core-spec",
        default=">=0.2,<0.3",
        help="Значение requires_core (по умолчанию '>=0.2,<0.3').",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Перезаписать существующий plugin.toml.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Не писать файл — только напечатать результат.",
    )
    args = parser.parse_args(list(argv) if argv is not None else None)

    rc = 0
    for plugin_dir in args.plugin_dirs:
        if not plugin_dir.is_dir():
            print(f"[skip] not a dir: {plugin_dir}", file=sys.stderr)
            rc = 1
            continue
        try:
            target, rendered = migrate_one(
                plugin_dir,
                core_spec=args.core_spec,
                overwrite=args.overwrite,
                dry_run=args.dry_run,
            )
        except (FileNotFoundError, FileExistsError, TypeError) as exc:
            print(f"[fail] {plugin_dir}: {exc}", file=sys.stderr)
            rc = 1
            continue
        action = "DRY-RUN" if args.dry_run else "WROTE"
        print(f"[{action}] {target}")
        if args.dry_run:
            print(rendered)
    return rc


if __name__ == "__main__":  # pragma: no cover — CLI entry point
    raise SystemExit(main())
