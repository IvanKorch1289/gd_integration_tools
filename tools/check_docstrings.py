"""Wave F.6 — docstring policy gate.

AST-проход по указанным каталогам. Каждый публичный класс / функция /
метод должен иметь docstring. Запрещены пустые / TODO / "Заглушка"
docstring'и.

Поведение:

* Возвращает exit code 0, если новых нарушений нет (по сравнению с
  ``tools/check_docstrings_allowlist.txt``).
* Exit code 1 — есть **новые** нарушения. Пишет diff в stderr.
* ``--update-allowlist`` — пересоздать allowlist из текущих нарушений
  (для амнистии baseline / после миграции модуля).
* ``--strict`` — игнорировать allowlist, любое нарушение → exit 1.

Использование:

  python tools/check_docstrings.py src/core src/dsl/engine src/core/interfaces
  python tools/check_docstrings.py src/core --strict
  python tools/check_docstrings.py src/core --update-allowlist
"""

from __future__ import annotations

import argparse
import ast
import re
import sys
from collections.abc import Iterable
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
ALLOWLIST_PATH = PROJECT_ROOT / "tools" / "check_docstrings_allowlist.txt"

# Запрещённые "пустые" docstring (case-insensitive).
_FORBIDDEN_PATTERN = re.compile(
    r"^\s*(todo|tbd|заглушка|placeholder|stub)\.?\s*$",
    re.IGNORECASE,
)


def _is_public_name(name: str) -> bool:
    """Публичность по PEP 8: не начинается с ``_`` или dunder."""
    return not name.startswith("_")


def _is_forbidden_docstring(text: str | None) -> bool:
    """``None`` / пустая / TODO-заглушка → True."""
    if text is None:
        return True
    stripped = text.strip()
    if not stripped:
        return True
    return bool(_FORBIDDEN_PATTERN.match(stripped))


def _walk_targets(roots: Iterable[Path]) -> list[Path]:
    """Собирает все ``*.py`` из переданных путей (всегда абсолютные)."""
    files: list[Path] = []
    for raw in roots:
        root = (PROJECT_ROOT / raw).resolve() if not raw.is_absolute() else raw.resolve()
        if root.is_file() and root.suffix == ".py":
            files.append(root)
        elif root.is_dir():
            files.extend(sorted(root.rglob("*.py")))
    return files


def _check_node(
    file: Path, node: ast.AST, parent: str = ""
) -> list[str]:
    """Проверяет ноду на наличие документированного docstring (recursive)."""
    violations: list[str] = []
    if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
        if _is_public_name(node.name):
            doc = ast.get_docstring(node)
            if _is_forbidden_docstring(doc):
                qualified = f"{parent}.{node.name}" if parent else node.name
                violations.append(
                    f"{file.relative_to(PROJECT_ROOT)}:{node.lineno}:"
                    f"{node.col_offset} {qualified}"
                )
        # Углубляемся в тело класса (методы), но не в функции (вложенные функции
        # обычно — приватные хелперы, проверяемые отдельно через _is_public_name).
        if isinstance(node, ast.ClassDef):
            new_parent = f"{parent}.{node.name}" if parent else node.name
            for child in node.body:
                violations.extend(_check_node(file, child, new_parent))
    return violations


def check_file(path: Path) -> list[str]:
    """Проверяет один Python-файл; возвращает список violations."""
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    except SyntaxError as exc:
        return [f"{path.relative_to(PROJECT_ROOT)}:syntax error: {exc.msg}"]

    violations: list[str] = []
    # Module-level docstring сейчас не required (есть headers / __all__).
    for node in tree.body:
        violations.extend(_check_node(path, node))
    return violations


def _load_allowlist() -> set[str]:
    if not ALLOWLIST_PATH.exists():
        return set()
    return {
        line.strip()
        for line in ALLOWLIST_PATH.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.startswith("#")
    }


def _save_allowlist(violations: list[str]) -> None:
    header = (
        "# Wave F.6 docstring amnesty baseline.\n"
        "# Содержит существующие нарушения, чтобы pre-push gate не блокировал\n"
        "# legacy-код. Снимать пункт по мере миграции модуля.\n"
        "# Формат: <relative_path>:<lineno>:<col> <qualified_name>\n\n"
    )
    body = "\n".join(sorted(set(violations)))
    ALLOWLIST_PATH.write_text(header + body + "\n", encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    """Точка входа CLI."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("paths", nargs="+", type=Path)
    parser.add_argument(
        "--update-allowlist", action="store_true", help="Перезаписать allowlist."
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Игнорировать allowlist; любое нарушение → exit 1.",
    )
    args = parser.parse_args(argv)

    files = _walk_targets(args.paths)
    if not files:
        print("[check_docstrings] нет .py-файлов в переданных путях", file=sys.stderr)
        return 0

    all_violations: list[str] = []
    for file in files:
        all_violations.extend(check_file(file))

    if args.update_allowlist:
        _save_allowlist(all_violations)
        print(
            f"[check_docstrings] allowlist обновлён: "
            f"{len(all_violations)} нарушений зафиксированы.",
            file=sys.stderr,
        )
        return 0

    if args.strict:
        if all_violations:
            for v in all_violations:
                print(v)
            print(
                f"[check_docstrings] strict mode: {len(all_violations)} нарушений.",
                file=sys.stderr,
            )
            return 1
        return 0

    allowlist = _load_allowlist()
    new_violations = [v for v in all_violations if v not in allowlist]
    if new_violations:
        print("[check_docstrings] НОВЫЕ нарушения (не в allowlist):", file=sys.stderr)
        for v in new_violations:
            print(v)
        print(
            "[check_docstrings] добавьте docstring или обновите allowlist через "
            "--update-allowlist (только при намеренной амнистии).",
            file=sys.stderr,
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
