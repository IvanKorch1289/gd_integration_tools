"""
Архитектурный линтер слоёв проекта согласно ADR-001.

Проверяет, что модули не нарушают границы слоёв Clean Architecture.

Разрешённые направления импортов:

    core/           → никуда (только stdlib и сторонние библиотеки)
    infrastructure/ → core/
    services/       → infrastructure/ + core/
    entrypoints/    → services/ + core/ + infrastructure (через DI)
    plugins/        → все слои (плагины интегрируют)

Запрещено:

    core/        импортирует из infrastructure/, entrypoints/, services/
    infrastructure/ импортирует из entrypoints/, services/
    services/    импортирует из entrypoints/

Скрипт сканирует исходные файлы через ``ast.parse`` (без выполнения кода),
собирает все импорты, сверяет их с матрицей разрешений и возвращает код
возврата 1 при обнаружении нарушений.

Запускается в CI и через pre-commit hook.

Пример использования::

    uv run python scripts/check_layers.py
    uv run python scripts/check_layers.py --root src
    uv run python scripts/check_layers.py --strict   # также проверять entrypoints→infrastructure
"""

from __future__ import annotations

import argparse
import ast
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

# Корень проекта (родитель директории scripts/).
PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SOURCE_ROOT = PROJECT_ROOT / "src"

# Допустимые top-level модули для импорта (без префикса src./app.).
# Если модуль не из этого списка — считается сторонним и игнорируется.
KNOWN_LAYER_MODULES = frozenset(
    {
        "core",
        "infrastructure",
        "services",
        "entrypoints",
        "dsl",
        "schemas",
        "tools",
        "utilities",
        "workflows",
        "plugins",
        "main",
    }
)

# Матрица разрешений: для каждого слоя перечисляем запрещённые цели.
# Слои, отсутствующие в ключах, проверке не подвергаются.
FORBIDDEN_IMPORTS: dict[str, frozenset[str]] = {
    "core": frozenset(
        {"infrastructure", "services", "entrypoints", "dsl", "workflows"}
    ),
    "infrastructure": frozenset({"services", "entrypoints", "workflows"}),
    "services": frozenset({"entrypoints"}),
    "dsl": frozenset({"entrypoints"}),
}

# Strict-матрица: дополнительные запреты, активные при --strict.
# Цель — полная инверсия зависимостей: entrypoints не знает об infrastructure,
# а только через core.interfaces + DI.
STRICT_FORBIDDEN_IMPORTS: dict[str, frozenset[str]] = {
    "entrypoints": frozenset({"infrastructure"}),
}

# Composition-root файлы — точки сборки приложения, которым по Clean
# Architecture разрешено знать обо всех слоях. Это "main" слой в
# терминологии Роберта Мартина: собирает зависимости и запускает систему.
#
# Пути указываются относительно корня проекта. Поддерживается wildcards.
COMPOSITION_ROOT_FILES: frozenset[str] = frozenset(
    {
        # FastAPI application factory — подключает middleware, роуты,
        # graphql/grpc/soap/sse/websocket/webhook/filewatcher/cdc.
        "src/infrastructure/application/app_factory.py",
        # Lifespan / startup / shutdown — инициализирует инфраструктуру
        # и регистрирует сервисы в DI-контейнере.
        "src/infrastructure/application/lifecycle.py",
        # DI composition root — связывает singletons из infrastructure,
        # security, dsl с FastAPI через app.state.
        "src/infrastructure/application/di.py",
        # Service registration — регистрирует все бизнес-сервисы в svcs.
        "src/infrastructure/application/service_setup.py",
        # Infrastructure bootstrap — поднимает внешние клиенты.
        "src/infrastructure/setup_infra.py",
        # DSL command setup — регистрирует action handlers и их схемы.
        "src/dsl/commands/setup.py",
    }
)


@dataclass(slots=True, frozen=True)
class Violation:
    """Описание одного нарушения архитектурных границ."""

    file: Path
    lineno: int
    source_layer: str
    imported: str
    target_layer: str


def _iter_python_files(roots: Iterable[Path]) -> list[Path]:
    """Собирает список .py файлов в указанных корневых директориях."""
    files: list[Path] = []
    for root in roots:
        if not root.exists():
            continue
        files.extend(sorted(root.rglob("*.py")))
    return files


def _classify_module(module: str) -> str | None:
    """
    Определяет слой по имени модуля.

    Поддерживает оба префикса, исторически встречающихся в проекте:
    ``src.X.*`` и ``app.X.*`` — обе формы дают одинаковый слой ``X``.

    Args:
        module: Имя модуля, например ``src.infrastructure.db.database``.

    Returns:
        Имя слоя (``core``, ``infrastructure`` и т.п.) либо ``None``,
        если модуль не принадлежит проекту.
    """
    parts = module.split(".")
    # Снимаем префикс src. или app.
    if parts and parts[0] in {"src", "app"} and len(parts) >= 2:
        candidate = parts[1]
    elif parts:
        candidate = parts[0]
    else:
        return None
    if candidate in KNOWN_LAYER_MODULES:
        return candidate
    return None


def _layer_of_file(path: Path, source_root: Path) -> str | None:
    """
    Определяет, к какому слою относится конкретный файл по его пути.

    Args:
        path: Абсолютный путь к .py файлу.
        source_root: Корень исходников (обычно ``src/``).

    Returns:
        Имя слоя или ``None`` если файл вне известных слоёв.
    """
    try:
        relative = path.resolve().relative_to(source_root.resolve())
    except ValueError:
        return None
    parts = relative.parts
    if not parts:
        return None
    candidate = parts[0]
    if candidate in KNOWN_LAYER_MODULES:
        return candidate
    return None


def _extract_imports(tree: ast.AST) -> list[tuple[int, str]]:
    """Возвращает список (lineno, dotted_module) всех импортов AST."""
    imports: list[tuple[int, str]] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            if node.module:
                imports.append((node.lineno, node.module))
        elif isinstance(node, ast.Import):
            for alias in node.names:
                imports.append((node.lineno, alias.name))
    return imports


def _is_composition_root(path: Path) -> bool:
    """Проверяет, является ли файл composition root (exempt от проверки)."""
    try:
        relative = path.resolve().relative_to(PROJECT_ROOT).as_posix()
    except ValueError:
        return False
    return relative in COMPOSITION_ROOT_FILES


def _check_file(
    path: Path, source_root: Path, forbidden: dict[str, frozenset[str]]
) -> list[Violation]:
    """Проверяет один файл на нарушение архитектурных границ."""
    if _is_composition_root(path):
        return []
    layer = _layer_of_file(path, source_root)
    if layer is None or layer not in forbidden:
        return []
    try:
        source = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return []
    try:
        tree = ast.parse(source, filename=str(path))
    except SyntaxError:
        return []

    forbidden_targets = forbidden[layer]
    issues: list[Violation] = []
    for lineno, module in _extract_imports(tree):
        target = _classify_module(module)
        if target is None or target == layer:
            continue
        if target in forbidden_targets:
            issues.append(
                Violation(
                    file=path,
                    lineno=lineno,
                    source_layer=layer,
                    imported=module,
                    target_layer=target,
                )
            )
    return issues


def check_layers(
    source_root: Path = DEFAULT_SOURCE_ROOT, *, strict: bool = False
) -> list[Violation]:
    """
    Выполняет проверку всех файлов под ``source_root``.

    Args:
        source_root: Корневая директория исходников (``src/``).
        strict: Включить строгий режим (дополнительные запреты).

    Returns:
        Список обнаруженных нарушений.
    """
    forbidden: dict[str, frozenset[str]] = dict(FORBIDDEN_IMPORTS)
    if strict:
        for layer, targets in STRICT_FORBIDDEN_IMPORTS.items():
            forbidden[layer] = forbidden.get(layer, frozenset()) | targets

    violations: list[Violation] = []
    for file_path in _iter_python_files([source_root]):
        violations.extend(_check_file(file_path, source_root, forbidden))
    return violations


def main(argv: list[str] | None = None) -> int:
    """
    CLI-точка входа линтера слоёв.

    Returns:
        0 если нарушений не найдено, 1 если найдены.
    """
    parser = argparse.ArgumentParser(
        description=(
            "Архитектурный линтер слоёв согласно ADR-001. "
            "Запрещает импорты между слоями, нарушающие направление зависимостей."
        )
    )
    parser.add_argument(
        "--root",
        type=Path,
        default=DEFAULT_SOURCE_ROOT,
        help=f"Корень исходников. По умолчанию: {DEFAULT_SOURCE_ROOT}",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Включить строгий режим: entrypoints не импортирует infrastructure.",
    )
    args = parser.parse_args(argv)

    violations = check_layers(args.root, strict=args.strict)

    if not violations:
        print("Нарушений не найдено.")
        return 0

    print(f"Найдено {len(violations)} нарушений архитектурных границ:", file=sys.stderr)
    for v in violations:
        rel = v.file.relative_to(PROJECT_ROOT) if v.file.is_absolute() else v.file
        print(
            f"  {rel}:{v.lineno}: слой '{v.source_layer}' "
            f"импортирует '{v.imported}' (слой '{v.target_layer}')",
            file=sys.stderr,
        )
    return 1


if __name__ == "__main__":
    sys.exit(main())
