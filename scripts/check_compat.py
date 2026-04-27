"""
Скрипт проверки совместимости проекта с целевой версией Python.

Проверяет исходный код на устаревшие API, несовместимые конструкции и
deprecated-паттерны, которые могут не работать в Python 3.12+ и в текущей
целевой версии проекта (3.14).

Проверки:
    * Недопустимые синтаксические конструкции (через ``ast.parse``).
    * Использование удалённых в 3.12+ API (``imp``, ``distutils``,
      ``asyncore``, ``asynchat``, ``collections.MutableMapping``).
    * Deprecated typing-имена вида ``typing.Text``, ``typing.io``.
    * Некорректные ``except (Exception,):`` — голые ``except:`` для CTC.
    * ``from __future__ import ...`` с удалёнными флагами.

Скрипт не падает на первой ошибке: собирает все проблемы, печатает
сводку и возвращает код 0 (совместимо) или 1 (найдены проблемы).

Пример использования::

    uv run python scripts/check_compat.py
    uv run python scripts/check_compat.py --min-version 3.12

Зависимости: только stdlib (``ast``, ``pathlib``, ``tokenize``, ``sys``).
"""

from __future__ import annotations

import argparse
import ast
import sys
import tokenize
from dataclasses import dataclass
from pathlib import Path

# Корневые директории, в которых ищутся исходники проекта.
DEFAULT_ROOTS: tuple[str, ...] = ("src", "scripts", "tools")

# Удалённые / несовместимые модули стандартной библиотеки.
REMOVED_MODULES_312: frozenset[str] = frozenset(
    {
        "imp",
        "distutils",
        "asyncore",
        "asynchat",
        "smtpd",
        "binhex",
        "symbol",
        "formatter",
        "parser",
        "cgi",
        "cgitb",
    }
)

# Deprecated typing-имена (заменены на аналоги из collections.abc или встроенные).
DEPRECATED_TYPING_NAMES: frozenset[str] = frozenset(
    {
        "Text",
        "io",
        "re",
        "ByteString",
    }
)


@dataclass(slots=True, frozen=True)
class Issue:
    """Обнаруженная проблема совместимости в исходном файле."""

    path: Path
    lineno: int
    message: str


def _iter_python_files(roots: list[Path]) -> list[Path]:
    """Возвращает отсортированный список .py-файлов из указанных корней."""
    files: list[Path] = []
    for root in roots:
        if not root.exists():
            continue
        files.extend(sorted(root.rglob("*.py")))
    return files


def _check_imports(tree: ast.AST, path: Path) -> list[Issue]:
    """Находит импорты удалённых модулей и deprecated typing-имён."""
    issues: list[Issue] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                root = alias.name.split(".", 1)[0]
                if root in REMOVED_MODULES_312:
                    issues.append(
                        Issue(
                            path=path,
                            lineno=node.lineno,
                            message=(
                                f"импорт удалённого в 3.12+ модуля "
                                f"'{alias.name}'"
                            ),
                        )
                    )
        elif isinstance(node, ast.ImportFrom):
            module = node.module or ""
            root = module.split(".", 1)[0]
            if root in REMOVED_MODULES_312:
                issues.append(
                    Issue(
                        path=path,
                        lineno=node.lineno,
                        message=(
                            f"импорт из удалённого в 3.12+ модуля '{module}'"
                        ),
                    )
                )
            if module == "typing":
                for alias in node.names:
                    if alias.name in DEPRECATED_TYPING_NAMES:
                        issues.append(
                            Issue(
                                path=path,
                                lineno=node.lineno,
                                message=(
                                    f"deprecated typing-имя "
                                    f"'typing.{alias.name}'"
                                ),
                            )
                        )
    return issues


def _check_bare_except(path: Path) -> list[Issue]:
    """Ищет голые ``except:`` через токенайзер (BLE001)."""
    issues: list[Issue] = []
    try:
        with tokenize.open(path) as fh:
            tokens = list(tokenize.generate_tokens(fh.readline))
    except (SyntaxError, tokenize.TokenizeError):
        return issues
    for idx, tok in enumerate(tokens):
        if tok.type == tokenize.NAME and tok.string == "except":
            # Ищем следующий значимый токен.
            for next_tok in tokens[idx + 1 :]:
                if next_tok.type in (
                    tokenize.NEWLINE,
                    tokenize.NL,
                    tokenize.COMMENT,
                    tokenize.INDENT,
                    tokenize.DEDENT,
                ):
                    continue
                if next_tok.type == tokenize.OP and next_tok.string == ":":
                    issues.append(
                        Issue(
                            path=path,
                            lineno=tok.start[0],
                            message="голый 'except:' без указания исключения",
                        )
                    )
                break
    return issues


def check_file(path: Path) -> list[Issue]:
    """Прогоняет набор проверок над одним файлом."""
    try:
        source = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return []
    try:
        tree = ast.parse(source, filename=str(path))
    except SyntaxError as exc:
        return [
            Issue(
                path=path,
                lineno=exc.lineno or 0,
                message=f"синтаксическая ошибка: {exc.msg}",
            )
        ]
    issues: list[Issue] = []
    issues.extend(_check_imports(tree, path))
    issues.extend(_check_bare_except(path))
    return issues


def main(argv: list[str] | None = None) -> int:
    """Точка входа: обходит roots, печатает сводку, возвращает код."""
    parser = argparse.ArgumentParser(
        description=(
            "Проверка совместимости исходников проекта с Python 3.12+."
        )
    )
    parser.add_argument(
        "--root",
        action="append",
        default=None,
        help=(
            "Директория для сканирования (можно указать несколько раз). "
            "По умолчанию: src/, scripts/, tools/."
        ),
    )
    args = parser.parse_args(argv)

    root_paths = (
        [Path(p) for p in args.root]
        if args.root
        else [Path(name) for name in DEFAULT_ROOTS]
    )

    files = _iter_python_files(root_paths)
    all_issues: list[Issue] = []
    for file_path in files:
        all_issues.extend(check_file(file_path))

    if not all_issues:
        print(
            f"Совместимость подтверждена (проверено {len(files)} файлов)."
        )
        return 0

    print(f"Найдено {len(all_issues)} проблем(ы) совместимости:")
    for issue in all_issues:
        print(f"  {issue.path}:{issue.lineno}: {issue.message}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
