#!/usr/bin/env python3
"""Генератор release-notes из Conventional Commits в git log.

Зачем
----
``make release-notes`` (make/quickwins.mk) ссылался на ``tools/changelog_autogen.py``,
которого в репозитории не было: цель всегда падала с
«No such file or directory». Этот модуль — каноническая реализация.

Использование
-------------
::

    python tools/changelog_autogen.py                        # HEAD, начиная с прошлого тега
    python tools/changelog_autogen.py --from v0.19.0 --to v0.20.0
    python tools/changelog_autogen.py --output dist/release-notes.md

Контракт
--------
* типы коммитов группируются в фиксированном порядке (feat → fix → … → Прочее);
* коммиты без Conventional-Commit-префикса попадают в группу «Прочее»;
* порядок внутри группы — от новых к старым (обратный хронологический);
* вывод детерминирован (без времени и окружения) — пригоден для diff;

Exit codes:
    0 — release-notes построены;
    1 — ошибка git (недоступный ref, не git-репозиторий);
    2 — ошибка аргументов/ввода-вывода.
"""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

__all__ = ("COMMIT_TYPES", "build_release_notes", "parse_commit", "main")

#: Группы типов коммитов и их порядок в отчёте.
COMMIT_TYPES: tuple[tuple[str, str], ...] = (
    ("feat", "Новые возможности"),
    ("fix", "Исправления"),
    ("perf", "Производительность"),
    ("refactor", "Рефакторинг"),
    ("docs", "Документация"),
    ("test", "Тесты"),
    ("build", "Сборка"),
    ("ci", "CI/CD"),
    ("chore", "Обслуживание"),
)

#: Conventional Commit: ``type(scope)!: subject``.
_COMMIT_RE = re.compile(
    r"^(?P<type>[a-zA-Z]+)"
    r"(?:\((?P<scope>[^)]*)\))?"
    r"(?P<breaking>!)?"
    r":\s*(?P<subject>.+)$"
)

#: Разделитель полей в выводе ``git log``.
_FIELD_SEP = "\x1f"


def _git(*args: str, cwd: Path | None = None) -> str:
    """Выполнить git-команду и вернуть stdout.

    Args:
        args: Аргументы git (без подкоманды ``git``).
        cwd: Рабочий каталог.

    Returns:
        stdout без хвостовых переводов строк.

    Raises:
        RuntimeError: git завершился с ненулевым кодом или недоступен.

    """
    try:
        proc = subprocess.run(  # noqa: S603  # dev-tool: фиксированная команда
            ["git", *args],  # noqa: S607  # dev-tool: git — PATH binary
            cwd=cwd,
            capture_output=True,
            text=True,
            check=False,
            encoding="utf-8",
            errors="replace",
        )
    except OSError as exc:
        raise RuntimeError(f"git недоступен: {exc}") from exc
    if proc.returncode != 0:
        raise RuntimeError(
            f"git {' '.join(args)} завершился с кодом {proc.returncode}: "
            f"{proc.stderr.strip()}"
        )
    return proc.stdout


def parse_commit(subject: str) -> tuple[str, str | None, str, bool]:
    """Разобрать subject коммита.

    Args:
        subject: Текст subject-а коммита.

    Returns:
        Кортеж ``(type, scope, subject, breaking)``. Для нестандартного
        subject тип = ``other``, breaking = False.

    """
    match = _COMMIT_RE.match(subject.strip())
    if match is None:
        return "other", None, subject.strip(), False
    scope = match.group("scope")
    return (
        match.group("type").lower(),
        scope or None,
        match.group("subject").strip(),
        bool(match.group("breaking")),
    )


def _resolve_from(to_ref: str, cwd: Path) -> str | None:
    """Найти ближайший предыдущий тег относительно ``to_ref``.

    Args:
        to_ref: Верхняя граница диапазона.
        cwd: Каталог репозитория.

    Returns:
        Тег или ``None``, если тегов нет.

    """
    try:
        out = _git("describe", "--tags", "--abbrev=0", f"{to_ref}^", cwd=cwd).strip()
    except RuntimeError:
        return None
    return out or None


def _collect_commits(from_ref: str | None, to_ref: str, cwd: Path) -> list[str]:
    """Собрать subject'ы коммитов диапазона.

    Args:
        from_ref: Нижняя граница диапазона (None — от корня репозитория).
        to_ref: Верхняя граница диапазона.
        cwd: Каталог репозитория.

    Returns:
        Список subject'ов, от новых к старым.

    """
    revision = f"{from_ref}..{to_ref}" if from_ref else to_ref
    out = _git("log", f"--pretty=format:%s{_FIELD_SEP}%H", revision, cwd=cwd)
    return [line.split(_FIELD_SEP)[0] for line in out.splitlines() if line.strip()]


def build_release_notes(subjects: list[str], title: str = "Release notes") -> str:
    """Собрать markdown-отчёт по subject'ам коммитов.

    Args:
        subjects: Subject'ы коммитов (от новых к старым).
        title: Заголовок отчёта.

    Returns:
        Markdown-текст release-notes.

    """
    groups: dict[str, list[str]] = {}
    for subject in subjects:
        ctype, scope, text, breaking = parse_commit(subject)
        entry = f"- {text}"
        if scope:
            entry = f"- ({scope}) {text}"
        if breaking:
            entry += " **BREAKING**"
        groups.setdefault(ctype, []).append(entry)

    lines: list[str] = [f"# {title}", ""]
    if not groups:
        lines.append("_Нет коммитов в диапазоне._")
        lines.append("")
        return "\n".join(lines)

    for ctype, heading in COMMIT_TYPES:
        entries = groups.pop(ctype, None)
        if not entries:
            continue
        lines.append(f"## {heading} ({ctype})")
        lines.append("")
        lines.extend(entries)
        lines.append("")

    other = groups.pop("other", None)
    if other:
        lines.append("## Прочее")
        lines.append("")
        lines.extend(other)
        lines.append("")

    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    """CLI-точка входа.

    Args:
        argv: Аргументы командной строки.

    Returns:
        0 — успех, 1 — ошибка git, 2 — ошибка аргументов/ввода-вывода.

    """
    parser = argparse.ArgumentParser(description="Generate release notes from git log")
    parser.add_argument(
        "--from", dest="from_ref", default=None, help="нижняя граница (тег/ревизия)"
    )
    parser.add_argument(
        "--to",
        dest="to_ref",
        default="HEAD",
        help="верхняя граница (по умолчанию HEAD)",
    )
    parser.add_argument(
        "--output",
        dest="output",
        default=None,
        help="файл вывода (по умолчанию stdout)",
    )
    parser.add_argument("--title", default="Release notes", help="заголовок отчёта")
    parser.add_argument(
        "--repo", default=".", help="каталог git-репозитория (по умолчанию текущий)"
    )
    args = parser.parse_args(argv)

    cwd = Path(args.repo).resolve()
    try:
        from_ref = args.from_ref or _resolve_from(args.to_ref, cwd)
        subjects = _collect_commits(from_ref, args.to_ref, cwd)
    except RuntimeError as exc:
        print(f"[changelog_autogen] ERROR: {exc}", file=sys.stderr)
        return 1

    notes = build_release_notes(subjects, title=args.title)
    if args.output:
        try:
            output = Path(args.output)
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(notes, encoding="utf-8")
        except OSError as exc:
            print(
                f"[changelog_autogen] ERROR: не удалось записать {args.output}: {exc}",
                file=sys.stderr,
            )
            return 2
        print(f"[changelog_autogen] Written: {args.output}")
    else:
        sys.stdout.write(notes)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
