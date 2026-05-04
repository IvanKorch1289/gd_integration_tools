"""Wave R1.2 — экспорт V11-артефактов в ``docs/reference/``.

Три цели Makefile:

* ``make plugin-schema`` → ``docs/reference/schemas/plugin.toml.schema.json``
* ``make route-schema`` → ``docs/reference/schemas/route.toml.schema.json``
* ``make capability-catalog`` → ``docs/reference/capabilities.md``

Все артефакты детерминированные (стабильный порядок ключей в JSON,
отсортированный список capability), коммитятся в репозиторий — IDE и
DSL-Linter читают их напрямую.

Запуск::

    uv run python tools/export_v11_artefacts.py plugin-schema
    uv run python tools/export_v11_artefacts.py route-schema
    uv run python tools/export_v11_artefacts.py capability-catalog
    uv run python tools/export_v11_artefacts.py all
"""

from __future__ import annotations

import argparse
import json
from collections.abc import Iterable
from pathlib import Path

from src.core.security.capabilities import build_default_vocabulary
from src.services.plugins.manifest_v11 import PluginManifestV11
from src.services.routes.manifest_v11 import RouteManifestV11

__all__ = (
    "export_capability_catalog",
    "export_plugin_schema",
    "export_route_schema",
    "main",
)

ROOT = Path(__file__).resolve().parents[1]
SCHEMAS_DIR = ROOT / "docs" / "reference" / "schemas"
CAPABILITIES_MD = ROOT / "docs" / "reference" / "capabilities.md"


def export_plugin_schema(
    target: Path = SCHEMAS_DIR / "plugin.toml.schema.json",
) -> Path:
    """Дамп JSON-Schema для ``plugin.toml`` (ADR-042)."""
    target.parent.mkdir(parents=True, exist_ok=True)
    schema = PluginManifestV11.model_json_schema()
    target.write_text(
        json.dumps(schema, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return target


def export_route_schema(target: Path = SCHEMAS_DIR / "route.toml.schema.json") -> Path:
    """Дамп JSON-Schema для ``route.toml`` (ADR-043)."""
    target.parent.mkdir(parents=True, exist_ok=True)
    schema = RouteManifestV11.model_json_schema()
    target.write_text(
        json.dumps(schema, indent=2, ensure_ascii=False, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return target


def export_capability_catalog(target: Path = CAPABILITIES_MD) -> Path:
    """Сгенерировать ``docs/reference/capabilities.md`` из vocabulary."""
    target.parent.mkdir(parents=True, exist_ok=True)
    vocab = build_default_vocabulary()
    rows: list[str] = []
    rows.append("# Capability catalog (V11 / ADR-044)")
    rows.append("")
    rows.append(
        "Сгенерировано `tools/export_v11_artefacts.py capability-catalog`. "
        "Не редактировать вручную."
    )
    rows.append("")
    rows.append("| Capability | scope_required | matcher | public | Описание |")
    rows.append("|---|---|---|---|---|")
    for definition in sorted(vocab.all(), key=lambda d: d.name):
        matcher_name = type(definition.matcher).__name__
        rows.append(
            f"| `{definition.name}` "
            f"| {'✅' if definition.scope_required else '➖'} "
            f"| `{matcher_name}` "
            f"| {'✅' if definition.public else '➖'} "
            f"| {definition.description} |"
        )
    rows.append("")
    target.write_text("\n".join(rows), encoding="utf-8")
    return target


_TARGETS = {
    "plugin-schema": export_plugin_schema,
    "route-schema": export_route_schema,
    "capability-catalog": export_capability_catalog,
}


def main(argv: Iterable[str] | None = None) -> int:
    """CLI entry point."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "target",
        choices=(*_TARGETS.keys(), "all"),
        help="Какой артефакт экспортировать.",
    )
    args = parser.parse_args(list(argv) if argv is not None else None)
    targets = (
        list(_TARGETS.values()) if args.target == "all" else [_TARGETS[args.target]]
    )
    for func in targets:
        path = func()
        print(f"[wrote] {path.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":  # pragma: no cover — CLI entry point
    raise SystemExit(main())
