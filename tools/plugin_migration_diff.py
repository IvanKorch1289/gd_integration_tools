"""Sprint 14 K5 W1 — генератор migration guide для плагинов.

Назначение:
    Сравнивает 2 версии ``plugin.toml`` одного и того же плагина и
    выдаёт markdown-отчёт с breaking-changes:

    * capability added/removed/scope-changed;
    * provides.{actions,processors,...} added/removed (removed = breaking);
    * requires_core widening/narrowing;
    * requires_plugins added/removed/changed.

Использование (CLI):
    python -m tools.plugin_migration_diff \\
        --plugin credit_pipeline \\
        --from-toml extensions/credit_pipeline/plugin.toml@1.0.0 \\
        --to-toml extensions/credit_pipeline/plugin.toml@2.0.0

    # Если нет 2-х файлов — можно через git revision:
    python -m tools.plugin_migration_diff \\
        --plugin credit_pipeline \\
        --from-ref v1.0.0 --to-ref HEAD

Output:
    Markdown печатается в stdout; ``--out-file`` сохраняет в файл.

Зависимости:
    - Jinja2 (уже в стеке);
    - GitPython опционально для ``--from-ref/--to-ref``.
"""

from __future__ import annotations

import argparse
import datetime as _dt
import json
import logging
import subprocess
import sys
import tomllib
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from jinja2 import Environment, FileSystemLoader, StrictUndefined
from packaging.specifiers import InvalidSpecifier, SpecifierSet

__all__ = ("MigrationDiff", "MigrationDiffer", "render_guide")

_TEMPLATE_DIR = Path(__file__).resolve().parent / "templates"
_TEMPLATE_NAME = "plugin_migration_guide.md.j2"

_logger = logging.getLogger("tools.plugin_migration_diff")


@dataclass(slots=True, frozen=True)
class MigrationDiff:
    """Структурированный результат diff'а двух манифестов."""

    plugin: str
    from_version: str
    to_version: str
    payload: dict[str, Any]


class MigrationDiffer:
    """Алгоритм сравнения двух ``plugin.toml``-структур."""

    def diff(
        self, plugin: str, old_toml: Mapping[str, Any], new_toml: Mapping[str, Any]
    ) -> MigrationDiff:
        """Главный entry-point.

        Args:
            plugin: Имя плагина (для шапки отчёта).
            old_toml: Старый ``plugin.toml`` как dict (из tomllib).
            new_toml: Новый ``plugin.toml`` как dict.
        """
        payload: dict[str, Any] = {
            "capabilities": self._diff_capabilities(old_toml, new_toml),
            "provides_added": {},
            "provides_removed": {},
            "core": self._diff_core(old_toml, new_toml),
            "requires_plugins": self._diff_requires_plugins(old_toml, new_toml),
        }
        provides_added, provides_removed = self._diff_provides(old_toml, new_toml)
        payload["provides_added"] = provides_added
        payload["provides_removed"] = provides_removed
        payload["summary"] = self._build_summary(payload)
        payload["breaking_changes"] = self._collect_breaking(payload)
        payload["has_breaking"] = bool(payload["breaking_changes"])

        return MigrationDiff(
            plugin=plugin,
            from_version=str(old_toml.get("version", "?")),
            to_version=str(new_toml.get("version", "?")),
            payload=payload,
        )

    @staticmethod
    def _diff_capabilities(
        old_toml: Mapping[str, Any], new_toml: Mapping[str, Any]
    ) -> dict[str, Any]:
        old_caps = {
            (c.get("name"), c.get("scope")) for c in old_toml.get("capabilities", [])
        }
        new_caps = {
            (c.get("name"), c.get("scope")) for c in new_toml.get("capabilities", [])
        }
        old_names = {n for n, _ in old_caps}
        new_names = {n for n, _ in new_caps}
        added_names = new_names - old_names
        removed_names = old_names - new_names
        common = new_names & old_names

        scope_changed = []
        for name in common:
            old_scopes = {scope for n, scope in old_caps if n == name}
            new_scopes = {scope for n, scope in new_caps if n == name}
            if old_scopes != new_scopes:
                scope_changed.append(
                    {
                        "name": name,
                        "old_scope": ",".join(sorted(s or "" for s in old_scopes))
                        or None,
                        "new_scope": ",".join(sorted(s or "" for s in new_scopes))
                        or None,
                    }
                )

        return {
            "added": sorted(added_names),
            "removed": sorted(removed_names),
            "scope_changed": scope_changed,
        }

    @staticmethod
    def _diff_provides(
        old_toml: Mapping[str, Any], new_toml: Mapping[str, Any]
    ) -> tuple[dict[str, list[str]], dict[str, list[str]]]:
        added: dict[str, list[str]] = {}
        removed: dict[str, list[str]] = {}
        old = old_toml.get("provides", {}) or {}
        new = new_toml.get("provides", {}) or {}
        for kind in (
            "actions",
            "processors",
            "repositories",
            "sources",
            "sinks",
            "schemas",
        ):
            old_set = set(old.get(kind, ()) or ())
            new_set = set(new.get(kind, ()) or ())
            added_kind = sorted(new_set - old_set)
            removed_kind = sorted(old_set - new_set)
            if added_kind:
                added[kind] = added_kind
            if removed_kind:
                removed[kind] = removed_kind
        return added, removed

    @staticmethod
    def _diff_core(
        old_toml: Mapping[str, Any], new_toml: Mapping[str, Any]
    ) -> dict[str, Any]:
        old_spec = str(old_toml.get("requires_core", ""))
        new_spec = str(new_toml.get("requires_core", ""))
        widening = False
        narrowing = False
        try:
            old_set = SpecifierSet(old_spec) if old_spec else None
            new_set = SpecifierSet(new_spec) if new_spec else None
        except InvalidSpecifier:
            old_set = new_set = None
        if old_set is not None and new_set is not None and old_spec != new_spec:
            # Эвристика: если новый spec включает старый (по строке) → расширение.
            widening = str(old_set).count(",") > str(new_set).count(",")
            narrowing = not widening
        return {
            "old": old_spec,
            "new": new_spec,
            "widening": widening,
            "narrowing": narrowing,
        }

    @staticmethod
    def _diff_requires_plugins(
        old_toml: Mapping[str, Any], new_toml: Mapping[str, Any]
    ) -> dict[str, Any]:
        old_section = (old_toml.get("compatibility") or {}).get(
            "requires_plugins", {}
        ) or {}
        new_section = (new_toml.get("compatibility") or {}).get(
            "requires_plugins", {}
        ) or {}
        added: dict[str, str] = {}
        removed: dict[str, str] = {}
        changed: dict[str, dict[str, str]] = {}
        for name, spec in new_section.items():
            if name not in old_section:
                added[name] = spec
            elif old_section[name] != spec:
                changed[name] = {"old": old_section[name], "new": spec}
        for name, spec in old_section.items():
            if name not in new_section:
                removed[name] = spec
        return {"added": added, "removed": removed, "changed": changed}

    @staticmethod
    def _build_summary(payload: Mapping[str, Any]) -> dict[str, int]:
        caps = payload["capabilities"]
        return {
            "capabilities_added": len(caps["added"]),
            "capabilities_removed": len(caps["removed"]),
            "capabilities_changed": len(caps["scope_changed"]),
            "provides_added": sum(len(v) for v in payload["provides_added"].values()),
            "provides_removed": sum(
                len(v) for v in payload["provides_removed"].values()
            ),
            "requires_added": len(payload["requires_plugins"]["added"]),
            "requires_removed": len(payload["requires_plugins"]["removed"]),
            "requires_changed": len(payload["requires_plugins"]["changed"]),
            "core_changed": int(payload["core"]["old"] != payload["core"]["new"]),
        }

    @staticmethod
    def _collect_breaking(payload: Mapping[str, Any]) -> list[dict[str, str]]:
        breaking: list[dict[str, str]] = []
        for cap in payload["capabilities"]["removed"]:
            breaking.append(
                {
                    "kind": "capability removed",
                    "detail": f"capability `{cap}` removed — consumers lose access",
                }
            )
        for kind, names in payload["provides_removed"].items():
            for name in names:
                breaking.append(
                    {
                        "kind": f"{kind} removed",
                        "detail": f"`{name}` ({kind}) is no longer provided",
                    }
                )
        if payload["core"]["narrowing"]:
            breaking.append(
                {
                    "kind": "core narrowed",
                    "detail": (
                        f"requires_core narrowed from `{payload['core']['old']}` to "
                        f"`{payload['core']['new']}` — older core releases now incompatible"
                    ),
                }
            )
        for name, change in payload["requires_plugins"]["changed"].items():
            breaking.append(
                {
                    "kind": "dependency spec changed",
                    "detail": (
                        f"`{name}` spec `{change['old']}` → `{change['new']}` "
                        f"— upstream must satisfy new range"
                    ),
                }
            )
        return breaking


def render_guide(diff: MigrationDiff) -> str:
    """Рендерит markdown через Jinja2."""
    env = Environment(
        loader=FileSystemLoader(_TEMPLATE_DIR),
        undefined=StrictUndefined,
        autoescape=False,  # noqa: S701 — markdown output без HTML
        keep_trailing_newline=True,
    )
    template = env.get_template(_TEMPLATE_NAME)
    return template.render(
        plugin=diff.plugin,
        from_version=diff.from_version,
        to_version=diff.to_version,
        generated_at=_dt.datetime.now(tz=_dt.UTC).isoformat(timespec="seconds"),
        **diff.payload,
    )


def _load_toml(path: Path) -> dict[str, Any]:
    with path.open("rb") as fh:
        return tomllib.load(fh)


def _load_from_git_ref(ref: str, relative_path: Path) -> dict[str, Any]:
    """Считать ``plugin.toml`` из конкретного git-ref'а через ``git show``."""
    cmd = ["git", "show", f"{ref}:{relative_path}"]
    completed = subprocess.run(  # noqa: S603
        cmd, check=True, capture_output=True, text=False
    )
    return tomllib.loads(completed.stdout.decode("utf-8"))


def main(argv: list[str] | None = None) -> int:
    """CLI entrypoint."""
    parser = argparse.ArgumentParser(
        description="Generate plugin migration guide between two plugin.toml versions."
    )
    parser.add_argument("--plugin", required=True, help="Имя плагина.")
    parser.add_argument(
        "--from-toml", type=Path, default=None, help="Путь к старой версии plugin.toml"
    )
    parser.add_argument(
        "--to-toml", type=Path, default=None, help="Путь к новой версии plugin.toml"
    )
    parser.add_argument(
        "--from-ref",
        default=None,
        help="git revision со старой версией (extensions/<plugin>/plugin.toml)",
    )
    parser.add_argument("--to-ref", default=None, help="git revision с новой версией")
    parser.add_argument(
        "--out-file",
        type=Path,
        default=None,
        help="Куда писать markdown (default — stdout).",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Печатать структурированный JSON вместо markdown.",
    )
    args = parser.parse_args(argv)

    relative_path = Path("extensions") / args.plugin / "plugin.toml"

    def _resolve_side(toml_path: Path | None, ref: str | None) -> dict[str, Any]:
        if toml_path is not None:
            return _load_toml(toml_path)
        if ref is not None:
            return _load_from_git_ref(ref, relative_path)
        raise SystemExit("Specify either --from-toml or --from-ref (same for to-).")

    old_toml = _resolve_side(args.from_toml, args.from_ref)
    new_toml = _resolve_side(args.to_toml, args.to_ref)

    differ = MigrationDiffer()
    diff = differ.diff(args.plugin, old_toml, new_toml)

    if args.json:
        output = json.dumps(
            {
                "plugin": diff.plugin,
                "from": diff.from_version,
                "to": diff.to_version,
                "payload": diff.payload,
            },
            indent=2,
            ensure_ascii=False,
        )
    else:
        output = render_guide(diff)

    if args.out_file is not None:
        args.out_file.write_text(output, encoding="utf-8")
        _logger.info("migration guide written to %s", args.out_file)
    else:
        print(output)
    return 0


if __name__ == "__main__":
    sys.exit(main())
