"""Wave R1.2a.b — конвертация ``dsl_routes/<x>.yaml`` → ``routes/<x>/``.

Каждый legacy YAML-маршрут (плоский ``dsl_routes/credit_pipeline.yaml``)
оборачивается в новую структуру ``routes/credit_pipeline/`` с manifest
``route.toml`` (см. ADR-043) и сохранением исходного payload как
``pipeline.dsl.yaml``. Поля manifest'а (``requires_core``,
``capabilities``, ``tenant_aware``, ``feature_flag``, ``tags``)
вставляются как placeholder'ы с комментариями для ручного дозаполнения.

Запуск::

    uv run python tools/migrate_dsl_routes_to_v11.py dsl_routes/ routes/
    uv run python tools/migrate_dsl_routes_to_v11.py dsl_routes/credit.yaml routes/ --dry-run
"""

from __future__ import annotations

import argparse
import shutil
import sys
from collections.abc import Iterable
from pathlib import Path

__all__ = ("main", "migrate_one", "render_toml")


def render_toml(*, name: str, version: str, requires_core: str) -> str:
    """Скелет ``route.toml`` для миграции legacy-маршрута."""
    return (
        f'name = "{name}"\n'
        f'version = "{version}"\n'
        f'requires_core = "{requires_core}"\n'
        "tenant_aware = false  # TODO Wave R1: подтвердить multi-tenancy semantics\n"
        '# TODO Wave R1: feature_flag = "ROUTE_<NAME>_ENABLED"\n'
        '# TODO Wave R1: tags = ["..."]\n'
        "\n"
        "# Главный pipeline-файл; добавить fragment-файлы в порядке загрузки.\n"
        'pipelines = ["pipeline.dsl.yaml"]\n'
        "\n"
        "# TODO Wave R1: задекларировать requires_plugins.\n"
        "# [requires_plugins]\n"
        '# bki_connector = ">=0.4,<1.0"\n'
        "\n"
        "# TODO Wave R1: capabilities ⊆ union(plugins).\n"
        "# [[capabilities]]\n"
        '# name = "db.read"\n'
        '# scope = "<dsn-alias>"\n'
    )


def migrate_one(
    legacy_yaml: Path,
    routes_dir: Path,
    *,
    core_spec: str,
    overwrite: bool,
    dry_run: bool,
) -> tuple[Path, str]:
    """Сконвертировать один файл ``dsl_routes/<x>.yaml`` → ``routes/<x>/``.

    Returns:
        ``(route_dir, rendered_toml)``.
    """
    if not legacy_yaml.is_file():
        raise FileNotFoundError(f"Legacy YAML not found: {legacy_yaml}")
    name = legacy_yaml.stem
    if name.endswith(".dsl"):
        name = name[: -len(".dsl")]
    target_dir = routes_dir / name
    target_toml = target_dir / "route.toml"
    target_pipeline = target_dir / "pipeline.dsl.yaml"

    if target_dir.exists() and not overwrite:
        raise FileExistsError(f"{target_dir} exists; pass --overwrite to replace")

    rendered = render_toml(name=name, version="1.0.0", requires_core=core_spec)
    if not dry_run:
        target_dir.mkdir(parents=True, exist_ok=overwrite)
        shutil.copy2(legacy_yaml, target_pipeline)
        target_toml.write_text(rendered, encoding="utf-8")
    return target_dir, rendered


def _expand_inputs(inputs: Iterable[Path]) -> list[Path]:
    """Принимает пути к файлам / каталогам / glob'ам, возвращает список YAML."""
    result: list[Path] = []
    for path in inputs:
        if path.is_file() and path.suffix in (".yaml", ".yml"):
            result.append(path)
        elif path.is_dir():
            result.extend(sorted(path.glob("*.yaml")))
            result.extend(sorted(path.glob("*.yml")))
    return result


def main(argv: Iterable[str] | None = None) -> int:
    """CLI entry point."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "inputs",
        nargs="+",
        type=Path,
        help="Файлы dsl_routes/<x>.yaml или каталог dsl_routes/.",
    )
    parser.add_argument("routes_dir", type=Path, help="Целевой каталог routes/.")
    parser.add_argument(
        "--core-spec",
        default=">=0.2,<0.3",
        help="Значение requires_core (по умолчанию '>=0.2,<0.3').",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Перезаписать существующий routes/<x>/.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Не писать файлы — только напечатать план.",
    )
    args = parser.parse_args(list(argv) if argv is not None else None)

    files = _expand_inputs(args.inputs)
    if not files:
        print("[skip] no YAML files matched", file=sys.stderr)
        return 1

    rc = 0
    for legacy in files:
        try:
            target_dir, rendered = migrate_one(
                legacy,
                args.routes_dir,
                core_spec=args.core_spec,
                overwrite=args.overwrite,
                dry_run=args.dry_run,
            )
        except (FileNotFoundError, FileExistsError) as exc:
            print(f"[fail] {legacy}: {exc}", file=sys.stderr)
            rc = 1
            continue
        action = "DRY-RUN" if args.dry_run else "MIGRATED"
        print(f"[{action}] {legacy} → {target_dir}")
        if args.dry_run:
            print(rendered)
    return rc


if __name__ == "__main__":  # pragma: no cover — CLI entry point
    raise SystemExit(main())
