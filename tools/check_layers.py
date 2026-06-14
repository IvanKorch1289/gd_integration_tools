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

LAYERS = (
    "core",
    "infrastructure",
    "services",
    "entrypoints",
    "schemas",
    "dsl",  # S65 W4: DSL — meta-layer, импортирует всё (orchestration)
    "workflows",  # S65 W4: workflows/ — meta-layer, импортирует всё
)
PLUGINS_LAYER = "plugins"
FRONTEND_LAYER = "frontend"
EXTENSIONS_LAYER = "extensions"  # S103 W1: extensions scanned by linter

ALLOWED: dict[str, set[str]] = {
    "core": set(),
    "infrastructure": {"core", "schemas"},
    "services": {"core", "schemas"},
    "entrypoints": {"services", "schemas", "core"},
    "schemas": {"core"},
    # S65 W4: DSL/workflows — meta-layers, оркестрирующие все backend слои.
    # Фактически могут импортировать любой слой (DSL строится поверх всего).
    "dsl": {"core", "infrastructure", "services", "entrypoints", "schemas"},
    "workflows": {"core", "infrastructure", "services", "entrypoints", "schemas"},
    # S103 W1: extensions — meta-layer, импортируют ТОЛЬКО core.
    # Корневая причина D5 split-brain: SQLAlchemy models живут в
    # infrastructure/, а extensions обязаны импортировать их для ORM.
    # Planned fix (S103+ W2+): переместить models в core/domain/models/
    # (DONE в S106 W2-W3).
    #
    # S110 W4: framework base classes (SQLAlchemyRepository,
    # main_session_manager, BaseService) — легитимное исключение.
    # Эти 3 класса являются framework primitives, которые extensions
    # обязаны наследовать/использовать для ORM/Service-логики.
    # Полный перенос в core/ нарушит layering (они используют
    # infrastructure-специфичные зависимости: SQLAlchemy, fastapi_filter,
    # ldap3). Facade pattern в core/ не уменьшает coupling, но создаёт
    # лишний indirection. См. ADR-0196 (Sprint 110 closure).
    "extensions": {"core"},
}
# S110 W4: точечные исключения для framework base classes.
# Применяется после основного ALLOWED check, только для extensions.
EXTENSIONS_FRAMEWORK_EXCEPTIONS: set[str] = {
    "src.backend.infrastructure.repositories.base",  # SQLAlchemyRepository
    "src.backend.infrastructure.database.session_manager",  # main_session_manager
    "src.backend.services.core.base",  # BaseService
    "src.backend.entrypoints.base",  # BaseEntrypoint (8 protocols)
    "src.backend.schemas.base",  # BaseSchema (Pydantic base)
    "src.backend.services.core.base_external_api",  # BaseExternalAPIClient
    "src.backend.services.auth.ad_directory_client",  # AdDirectoryClient
    # S110 W4: per-entity route schemas — extensions владеют
    # соответствующими сущностями, схемы должны быть доступны.
    "src.backend.schemas.route_schemas.orders",
    "src.backend.schemas.route_schemas.users",
    "src.backend.schemas.route_schemas.orderkinds",
    "src.backend.schemas.route_schemas.files",
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
    ``src/frontend/...``, ``extensions/...`` и legacy ``src/<layer>/...``.

    S103 W1: extensions layer detection — поддерживает 2 режима:
    1. ``--root extensions`` → rel path = "core_entities/...", нужно
       проверять ``root.name == EXTENSIONS_LAYER``.
    2. ``--root .`` → rel path = "extensions/...", нужно проверять
       ``rel.parts[0] == EXTENSIONS_LAYER``.
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
    # S103 W1: extensions — отдельный layer (root.name OR rel.parts[0])
    if root.name == EXTENSIONS_LAYER or rel.parts[0] == EXTENSIONS_LAYER:
        return EXTENSIONS_LAYER
    return None


def _imports(tree: ast.AST) -> Iterable[tuple[str, int, bool]]:
    """Yield (module, lineno, is_lazy) for each import.

    ``is_lazy`` = True if import is inside a function body (not at module level).
    S27: lazy imports inside functions are not checked (they resolve at runtime).
    """
    for node in ast.walk(tree):
        if not isinstance(node, (ast.Import, ast.ImportFrom)):
            continue
        module = getattr(node, "module", None)
        if not module:
            continue
        # Check if this import is nested inside a function (lazy import)
        is_lazy = _is_lazy_import(tree, node)
        yield module, node.lineno, is_lazy


def _is_lazy_import(tree: ast.AST, import_node: ast.AST) -> bool:
    """Проверяет, является ли import lazy (внутри тела функции)."""
    for node in ast.walk(tree):
        if not isinstance(node, ast.FunctionDef):
            continue
        for child in ast.walk(node):
            if child is import_node:
                return True
    return False


def _is_in_type_checking_block(tree: ast.AST, target_lineno: int) -> bool:
    """Проверяет, находится ли строка внутри ``if TYPE_CHECKING:`` блока.

    S27: TYPE_CHECKING импорты (например, ``DLQEnvelope`` в dlq_policy.py)
    не создают runtime-зависимостей и не должны считаться нарушениями слоёв.
    """
    for node in ast.walk(tree):
        if isinstance(node, ast.If):
            test = node.test
            if (
                isinstance(test, ast.Attribute)
                and isinstance(test.value, ast.Name)
                and test.value.id == "typing"
                and test.attr == "TYPE_CHECKING"
            ):
                if node.col_offset <= 0:  # top-level only
                    for child in ast.walk(node):
                        if isinstance(child, (ast.Import, ast.ImportFrom)):
                            if (
                                hasattr(child, "lineno")
                                and child.lineno == target_lineno
                            ):
                                return True
    return False


def _check_file(path: Path, root: Path) -> list[tuple[str, str, str]]:
    """Возвращает список нарушений вида (rel_path, importer_layer, imported)."""
    layer = _file_layer(path, root)
    if layer is None or layer == PLUGINS_LAYER:
        return []
    # S110 W1: test files inside extensions/ are allowed to import
    # from any layer (they test internals — fixture/manifest loaders
    # live in services/ for example). Production extension code still
    # must follow core-only rule.
    if layer == EXTENSIONS_LAYER and "/tests/" in str(path.as_posix()):
        return []
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except SyntaxError:
        return []
    violations: list[tuple[str, str, str]] = []
    rel = str(path.as_posix())

    # R3.10d: frontend проверяется по белому списку префиксов, не по слоям.
    if layer == FRONTEND_LAYER:
        for module, lineno, _is_lazy in _imports(tree):
            if module.startswith(("src.frontend", "app.frontend")):
                continue
            if not module.startswith(("src.backend", "app.backend", "src.", "app.")):
                continue
            if not module.startswith(FRONTEND_ALLOWED_PREFIXES):
                violations.append((rel, layer, module))
        return violations

    allowed = ALLOWED.get(layer, set())
    for module, lineno, is_lazy in _imports(tree):
        # S27 marker удалён S65 W2: lazy imports ДОЛЖНЫ проверяться
        # (раньше S27 их skip'ал, создавая blind spot). Теперь они
        # проходят через allowlist/fail-CI как обычные нарушения.
        # S27: TYPE_CHECKING импорты не считаются нарушениями
        if _is_in_type_checking_block(tree, lineno):
            continue
        # R3.10d: одностороннее правило — backend никогда не импортирует frontend.
        target = _layer_of(module)
        if target == FRONTEND_LAYER:
            violations.append((rel, layer, module))
            continue
        if target is None or target == layer or target == PLUGINS_LAYER:
            continue
        if target not in allowed:
            # S110 W4: framework base classes — легитимное исключение
            # для extensions (SQLAlchemyRepository, main_session_manager,
            # BaseService). См. EXTENSIONS_FRAMEWORK_EXCEPTIONS ниже.
            if (
                layer == EXTENSIONS_LAYER
                and module in EXTENSIONS_FRAMEWORK_EXCEPTIONS
            ):
                continue
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
    """S110 W2: MERGE new violations with existing allowlist (was REPLACE).

    Раньше ``--update-allowlist`` ПЕРЕЗАПИСЫВАЛ весь файл только новыми
    violations, теряя legacy 200+ entries из S103-S106 baseline.
    Теперь MERGE: existing + new = union, deduped, sorted.

    S112 W1: эта функция только MERGE'ит. Для удаления stale entries
    (allowlist entries, чьи violations больше не в коде) используй
    ``--prune-allowlist`` (вызывает :func:`_prune_allowlist`).
    """
    new_keys = set(keys)
    existing = _load_allowlist()
    merged = existing | new_keys
    sorted_keys = sorted(merged)
    body = (
        "# Allowlist архитектурных нарушений (Wave 1.3 baseline).\n"
        "# Формат: <rel_path>\\t<importer_layer>\\t<imported_module>\n"
        "# Цель — постепенно сокращать.\n"
        "# S110 W2: --update-allowlist MERGES (was REPLACE).\n"
        "# S112 W1: --prune-allowlist removes stale entries (complement to MERGE).\n"
    )
    ALLOWLIST_PATH.write_text(body + "\n".join(sorted_keys) + "\n", encoding="utf-8")


def _prune_allowlist(keys: Iterable[str]) -> int:
    """S112 W1: REMOVE stale entries из allowlist.

    Stale entry = entry в allowlist, для которой corresponding violation
    больше не существует в коде (refactored/removed).

    Args:
        keys: iterable of violation keys (current scan result).

    Returns:
        number of stale entries removed.

    Note:
        Сканирует ТОЛЬКО указанный root (default = ``src/``). Для full
        repo prune (когда allowlist содержит и src/, и extensions/
        entries) запускай с ``--root .`` или аналогичным путём,
        покрывающим обе директории.
    """
    current = set(keys)
    existing = _load_allowlist()
    stale = existing - current
    if not stale:
        return 0
    fresh = existing & current
    body = (
        "# Allowlist архитектурных нарушений (Wave 1.3 baseline).\n"
        "# Формат: <rel_path>\\t<importer_layer>\\t<imported_module>\n"
        "# Цель — постепенно сокращать.\n"
        "# S110 W2: --update-allowlist MERGES (was REPLACE).\n"
        "# S112 W1: --prune-allowlist removes stale entries (complement to MERGE).\n"
    )
    ALLOWLIST_PATH.write_text(body + "\n".join(sorted(fresh)) + "\n", encoding="utf-8")
    return len(stale)


def _collect_all_violations() -> set[str]:
    """S112 W1: scan full repo (src/ + extensions/) для root-agnostic prune.

    Returns:
        set of all current violation keys across both src/ and extensions/.
    """
    keys: set[str] = set()
    for root in (Path("src"), Path("extensions")):
        if not root.exists():
            continue
        for py in root.rglob("*.py"):
            if "__pycache__" in py.parts:
                continue
            for v in _check_file(py, root):
                keys.add(_violation_key(v))
    return keys


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    root = Path("src")
    update = "--update-allowlist" in args
    prune = "--prune-allowlist" in args
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

    if prune:
        # S112 W1: --prune-allowlist removes stale entries.
        # Используем FULL repo scan (src/ + extensions/) для root-agnostic
        # pruning, т.к. allowlist содержит mixed entries из обоих roots.
        all_keys = _collect_all_violations()
        removed = _prune_allowlist(all_keys)
        print(
            f"Allowlist pruned: removed {removed} stale entries → {ALLOWLIST_PATH}"
        )
        return 0

    # R3.10d: --strict игнорирует allowlist (CI/release-gate).
    allowlist: set[str] = set() if strict else _load_allowlist()
    new_violations = sorted(keys - allowlist)
    # S112 W1: стейл-проверка должна покрывать FULL repo (src/ + extensions/),
    # а не только текущий root — иначе src/ entries выглядят "стейл" при
    # ``--root extensions`` (false positive).
    if not strict:
        all_violations = _collect_all_violations()
        stale = sorted(allowlist - all_violations)
    else:
        stale = []

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
