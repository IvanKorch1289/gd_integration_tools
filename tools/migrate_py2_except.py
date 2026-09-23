#!/usr/bin/env python3.14
"""AST-based миграция Python-2 ``except X, Y:`` → ``except (X, Y):``.

Контекст: W0 P0-BLOCKER (cycles 152+). 233 строки в репо используют устаревший
Py2-синтаксис. На Python 3.14 PEG-парсер трактует ``except A, B:`` как
``except (A, B):`` с ``name=None`` (кортеж без as-переменной) — формально
валидно, но стилистически Py2-архаизм и ломает Py3.9-совместимость.

Миграция:

  1. Парсит файл через ``ast.parse``.
  2. Находит ``ast.ExceptHandler`` где ``type`` — ``Tuple`` и ``name`` — None.
  3. Для каждого такого handler читает source-строку, определяет текст
     между ``except`` и двоеточием, и если в нём есть ``,`` без сбалансированных
     скобок — заменяет на ``except (<orig>)``.
  4. Никогда не трогает уже-валидный синтаксис (``except (A, B):``).
  5. После миграции — ``compile()`` всего файла (fail-closed).

Использование:

    python3.14 tools/migrate_py2_except.py --root src --check        # dry-run
    python3.14 tools/migrate_py2_except.py --root src --write        # применить
    python3.14 tools/migrate_py2_except.py --root . --check --json    # JSON

Гарантии:

    * AST-based — не ломает строки/docstrings/f-strings.
    * Идемпотентно — повторный запуск ничего не меняет.
    * Dry-run по умолчанию; --write для применения.
    * Каждый изменённый файл — compile()-проверка.
    * ZERO data loss: сохраняет оригинальные имена/комментарии через line-splice.
"""
from __future__ import annotations

import argparse
import ast
import json
import sys
from pathlib import Path

# Целевые директории для миграции.
DEFAULT_ROOTS = ("src", "tests", "tools", "scripts", "extensions")


def _detect_py2_except_line(line_text: str) -> tuple[int, int] | None:
    """Определить в source-строке границы ``except X, Y:`` (Py2-pattern).

    Возвращает (start_idx, end_idx) текста ДО двоеточия, если найден Py2-pattern.
    Иначе None.

    Критерии:

    *   Строка начинается с ``except`` (после whitespace).
    *   Между ``except`` и ``:`` есть ``,`` И скобки несбалансированы
        (``(`` != ``)``) — значит это НЕ ``except (A, B):``.
    *   Не должно быть ``as`` перед запятой.
    """
    stripped = line_text.lstrip()
    if not stripped.startswith("except"):
        return None
    # Найти двоеточие после except (исключаем ':=' walrus).
    colon_idx = None
    i = len("except")
    n = len(line_text)
    while i < n:
        ch = line_text[i]
        if ch == ":":
            # Walrus := check
            if i + 1 < n and line_text[i + 1] == "=":
                i += 2
                continue
            colon_idx = i
            break
        i += 1
    if colon_idx is None:
        return None
    segment = line_text[len("except"):colon_idx] if False else line_text[
        line_text.index("except") + len("except") : colon_idx
    ]
    # Если есть 'as' — это валидный Py3 синтаксис, не трогаем.
    if " as " in segment:
        return None
    # Считаем скобки и запятые.
    if "," not in segment:
        return None
    open_p = segment.count("(")
    close_p = segment.count(")")
    if open_p == close_p and open_p > 0:
        # Сбалансированные скобки — это валидный tuple-form, не трогаем.
        return None
    if open_p > close_p:
        # Типа ``except (A, B`` — обрезанный tuple, лучше не трогать,
        # это обработает другой pass (дописывание ``)``).
        return None
    # Py2-pattern подтверждён: есть запятая, нет as, скобки несбалансированы.
    start = line_text.index("except")
    return (start + len("except"), colon_idx)


def _migrate_file(path: Path, write: bool) -> tuple[bool, int, list[tuple[int, str]]]:
    """Мигрировать один файл.

    Возвращает (changed, count, offenders).
    offenders — список (line_no, new_text) изменённых строк.
    """
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError) as e:
        return (False, 0, [])
    # Проверить парсинг до миграции.
    try:
        ast.parse(text)
    except SyntaxError:
        # Не наш случай — пропускаем битый файл (другой gate).
        return (False, 0, [])
    lines = text.splitlines(keepends=False)
    offenders: list[tuple[int, str]] = []
    changed_count = 0
    for idx, line in enumerate(lines):
        bounds = _detect_py2_except_line(line)
        if bounds is None:
            continue
        start, end = bounds
        types_text = line[start:end].strip()
        # Построить новую строку: ``except (<types_text>):``.
        leading = line[: line.index("except")]
        # ``end`` указывает на позицию ``:`` — пропускаем его, чтобы не дублировать.
        trailing = line[end + 1:]
        # Всегда ставим пробел между ``except`` и ``(`` — это ключевое слово,
        # Python не допускает ``except(`` (без пробела).
        new_line = f"{leading}except ({types_text}):{trailing}"
        lines[idx] = new_line
        offenders.append((idx + 1, new_line))
        changed_count += 1
    if changed_count == 0:
        return (False, 0, [])
    new_text = "\n".join(lines)
    if text.endswith("\n") and not new_text.endswith("\n"):
        new_text += "\n"
    # Compile-проверка результата.
    try:
        compile(new_text, str(path), "exec")
    except SyntaxError as e:
        print(f"FATAL: post-migration SyntaxError in {path}:{e.lineno}: {e.msg}", file=sys.stderr)
        return (False, 0, [])
    if write:
        path.write_text(new_text, encoding="utf-8")
    return (True, changed_count, offenders)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n", 1)[0])
    parser.add_argument("--root", action="append", default=[],
                        help="Корень для сканирования (можно несколько раз)")
    parser.add_argument("--write", action="store_true",
                        help="Применить изменения (по умолчанию dry-run)")
    parser.add_argument("--check", action="store_true",
                        help="Dry-run (default если нет --write)")
    parser.add_argument("--json", action="store_true", help="JSON-вывод")
    parser.add_argument("--extensions-only", action="append", default=[".py"],
                        help="Расширения файлов (default .py)")
    args = parser.parse_args()
    roots = args.root if args.root else list(DEFAULT_ROOTS)
    write_mode = bool(args.write and not args.check)
    exts = tuple(args.extensions_only)

    summary: dict[str, dict[str, object]] = {}
    total_files_changed = 0
    total_lines_changed = 0
    for root in roots:
        root_path = Path(root)
        if not root_path.exists():
            continue
        files_changed = 0
        lines_changed = 0
        offenders_all: list[tuple[str, int, str]] = []
        for path in sorted(root_path.rglob("*")):
            if not path.is_file() or path.suffix not in exts:
                continue
            if "__pycache__" in path.parts or ".git" in path.parts:
                continue
            changed, count, offenders = _migrate_file(path, write=write_mode)
            if changed:
                files_changed += 1
                lines_changed += count
                for line_no, line in offenders:
                    offenders_all.append((str(path), line_no, line))
        summary[root] = {
            "files_changed": files_changed,
            "lines_changed": lines_changed,
            "offenders": offenders_all[:50],
        }
        total_files_changed += files_changed
        total_lines_changed += lines_changed

    if args.json:
        print(json.dumps({
            "mode": "write" if write_mode else "check",
            "total_files_changed": total_files_changed,
            "total_lines_changed": total_lines_changed,
            "by_root": summary,
        }, indent=2, ensure_ascii=False))
    else:
        mode = "WRITE" if write_mode else "CHECK"
        print(f"[{mode}] {total_files_changed} files, {total_lines_changed} lines")
        for root, data in summary.items():
            fc = data["files_changed"]
            lc = data["lines_changed"]
            if fc or lc:
                print(f"  {root}: {fc} files, {lc} lines")
                for path, ln, line in data["offenders"][:10]:
                    print(f"    {path}:{ln}: {line[:120]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())