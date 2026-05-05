#!/usr/bin/env python3
"""Линтер архитектурных слоёв (ADR-001 / CLAUDE.md / Wave 1.3 / R3.10d).

Проверяет статически (через AST), что Python-файлы соблюдают правила
импорта между слоями:

* ``entrypoints/``    → разрешены ``services/``, ``schemas/``, ``core/``;
* ``services/``       → разрешены ``core/``, ``schemas/``;
* ``infrastructure/`` → разрешены ``core/``, ``schemas/``;
* ``core/``           → только stdlib и сторонние pip-пакеты (никаких
                        ``infrastructure/``, ``services/``, ``entrypoints/``);
* ``schemas/``        → разрешены ``core/``;
* ``plugins/``        → разрешено всё (sandbox);
* ``frontend/``       → разрешён только узкий публичный фасад backend:
                        ``src.backend.{core, services, schemas,
                        utilities.codecs}``;
* любой backend-слой ⊥ ``frontend/`` (одностороннее правило R3.10d).

После R3.10 layout: распознаются префиксы ``src.backend.<layer>``
и ``src.frontend.<...>`` (legacy ``src.<layer>`` остаётся
поддержанным для совместимости с переходным периодом).

Запуск::

    python tools/check_layers.py [--root SRC] [--update-allowlist] [--strict]

Поведение:

* allowlist лежит в ``tools/check_layers_allowlist.txt`` — известные
  legacy-нарушения; baseline создаётся ``--update-allowlist``;
* линтер падает (код 1) только на **новых** нарушениях, не входящих
  в allowlist;
* также падает, если в allowlist остались "стейл" записи (нарушение
  исправлено, запись забыли удалить) — следует обновить allowlist;
* ``--strict`` игнорирует allowlist (CI/release-gate).

Используется в CI и локально (см. ``Makefile`` цель ``layers``).
"""

from __future__ import annotations

import ast
import sys
from collections.abc import Iterable
from pathlib import Path

LAYERS = ("core", "infrastructure", "services", "entrypoints", "schemas")
PLUGINS_LAYER = "plugins"
FRONTEND_LAYER = "frontend"

ALLOWED: dict[str, set[str]] = {
    "core": set(),
    "infrastructure": {"core", "schemas"},
    "services": {"core", "schemas"},
    "entrypoints": {"services", "schemas", "core"},
    "schemas": {"core"},
}

# R3.10d: одностороннее правило frontend → узкий публичный фасад backend.
# Любой импорт из frontend, не попадающий под эти префиксы (кроме самого
# ``src.frontend``/``app.frontend``), считается нарушением.
FRONTEND_ALLOWED_PREFIXES: tuple[str, ...] = (
    "src.backend.core",
    "src.backend.services",
    "src.backend.schemas",
    "src.backend.utilities.codecs",
    "app.backend.core",
    "app.backend.services",
    "app.backend.schemas",
    "app.backend.utilities.codecs",
)

ALLOWLIST_PATH = Path(__file__).parent / "check_layers_allowlist.txt"


def _layer_of(module: str) -> str | None:
    """Определяет слой по dotted import-path.

    Понимает три формы:

    * ``src.backend.<layer>.X`` / ``app.backend.<layer>.X`` (R3.10+);
    * ``src.frontend.X`` / ``app.frontend.X`` → ``frontend``;
    * legacy ``src.<layer>.X`` / ``app.<layer>.X`` (до R3.10).
    """
    parts = module.split(".")
    if not parts:
        return None
    if parts[0] in {"src", "app"}:
        if len(parts) > 1 and parts[1] == "frontend":
            return FRONTEND_LAYER
        if len(parts) > 2 and parts[1] == "backend":
            candidate = parts[2]
        elif len(parts) > 1:
            candidate = parts[1]
        else:
            return None
    else:
        candidate = parts[0]
    if candidate in LAYERS or candidate == PLUGINS_LAYER:
        return candidate
    return None


def _file_layer(path: Path, root: Path) -> str | None:
    """Определяет слой по физическому пути файла.

    Поддерживает layout ``src/backend/<layer>/...`` (R3.10+),
    ``src/frontend/...`` и legacy ``src/<layer>/...``.
    """
    try:
        rel = path.relative_to(root)
    except ValueError:
        return None
    if not rel.parts:
        return None
    if rel.parts[0] == "frontend":
        return FRONTEND_LAYER
    if rel.parts[0] == "backend" and len(rel.parts) > 1:
        candidate = rel.parts[1]
    else:
        candidate = rel.parts[0]
    if candidate in LAYERS or candidate == PLUGINS_LAYER:
        return candidate
    return None


def _imports(tree: ast.AST) -> Iterable[tuple[str, int]]:
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                yield alias.name, node.lineno
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                yield node.module, node.lineno


def _check_file(path: Path, root: Path) -> list[tuple[str, str, str]]:
    """Возвращает список нарушений вида (rel_path, importer_layer, imported)."""
    layer = _file_layer(path, root)
    if layer is None or layer == PLUGINS_LAYER:
        return []
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except SyntaxError:
        return []
    violations: list[tuple[str, str, str]] = []
    rel = str(path.as_posix())

    # R3.10d: frontend проверяется по белому списку префиксов, не по слоям.
    if layer == FRONTEND_LAYER:
        for module, _lineno in _imports(tree):
            if module.startswith(("src.frontend", "app.frontend")):
                continue
            if not module.startswith(("src.backend", "app.backend", "src.", "app.")):
                continue
            if not module.startswith(FRONTEND_ALLOWED_PREFIXES):
                violations.append((rel, layer, module))
        return violations

    allowed = ALLOWED.get(layer, set())
    for module, _lineno in _imports(tree):
        # R3.10d: одностороннее правило — backend никогда не импортирует frontend.
        target = _layer_of(module)
        if target == FRONTEND_LAYER:
            violations.append((rel, layer, module))
            continue
        if target is None or target == layer or target == PLUGINS_LAYER:
            continue
        if target not in allowed:
            violations.append((rel, layer, module))
    return violations


def _violation_key(v: tuple[str, str, str]) -> str:
    """Стабильный ключ для allowlist (без lineno — устойчив к правкам)."""
    rel, layer, imported = v
    return f"{rel}\t{layer}\t{imported}"


def _load_allowlist() -> set[str]:
    if not ALLOWLIST_PATH.exists():
        return set()
    return {
        line.strip()
        for line in ALLOWLIST_PATH.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.startswith("#")
    }


def _save_allowlist(keys: Iterable[str]) -> None:
    sorted_keys = sorted(set(keys))
    body = (
        "# Allowlist архитектурных нарушений (Wave 1.3 baseline).\n"
        "# Формат: <rel_path>\\t<importer_layer>\\t<imported_module>\n"
        "# Цель — постепенно сокращать.\n"
    )
    ALLOWLIST_PATH.write_text(body + "\n".join(sorted_keys) + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    root = Path("src")
    update = "--update-allowlist" in args
    strict = "--strict" in args
    if "--root" in args:
        idx = args.index("--root")
        root = Path(args[idx + 1])
    if not root.exists():
        print(f"check_layers: root '{root}' не найден", file=sys.stderr)
        return 2

    violations: list[tuple[str, str, str]] = []
    for py in root.rglob("*.py"):
        if "__pycache__" in py.parts:
            continue
        violations.extend(_check_file(py, root))

    keys = {_violation_key(v) for v in violations}

    if update:
        _save_allowlist(keys)
        print(f"Allowlist обновлён: {len(keys)} запис(и/ей) → {ALLOWLIST_PATH}")
        return 0

    # R3.10d: --strict игнорирует allowlist (CI/release-gate).
    allowlist: set[str] = set() if strict else _load_allowlist()
    new_violations = sorted(keys - allowlist)
    stale = sorted(allowlist - keys) if not strict else []

    total_files = sum(1 for _ in root.rglob("*.py"))
    if not new_violations and not stale:
        mode = "strict" if strict else f"baseline: {len(allowlist)} legacy"
        print(f"Нарушений: 0 новых  (файлов: {total_files}; {mode})")
        return 0

    if new_violations:
        print(f"НОВЫЕ нарушения: {len(new_violations)}")
        for key in new_violations:
            rel, layer, imported = key.split("\t")
            print(f"  {rel}  {layer}/  →  {imported}")
    if stale:
        print(f"\nСТЕЙЛ записи в allowlist: {len(stale)} (исправлены — обновите)")
        for key in stale[:10]:
            rel, layer, imported = key.split("\t")
            print(f"  {rel}  {layer}/  →  {imported}")
        if len(stale) > 10:
            print(f"  ... и ещё {len(stale) - 10}")
        print("\nОбновить: python tools/check_layers.py --update-allowlist")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
