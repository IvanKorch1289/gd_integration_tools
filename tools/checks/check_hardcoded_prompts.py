#!/usr/bin/env python3
"""AST-checker hardcoded LLM-prompts (Wave 13 GAP-AI).

Сканирует Python-исходники и находит «зашитые» строковые промпты
для LLM, которые должны жить в Langfuse PromptRegistry / external store:

* keyword arguments с именами из ``PROMPT_KWARGS`` (``system_prompt``,
  ``system_message``, ``prompt``, ``instructions``, …) — литерал длиннее
  ``--min-length`` символов;
* позиционные args/kwargs известных функций сборки сообщений
  (``SystemMessage``, ``HumanMessage``, ``AIMessage``,
  ``ChatPromptTemplate.from_template``, ``ChatPromptTemplate.from_messages``).

Поддерживает:

* строковые литералы (``ast.Constant`` со ``str``);
* JoinedStr — конкатенация constant-частей f-строк (без вычислений);
* implicit concatenation (``"a" "b"`` → один ``Constant``).

Allowlist
---------
``tools/checks/prompt_allowlist.txt`` — список glob-масок (по одной на строку,
``#`` — комментарий). Файлы, соответствующие маске, пропускаются.

CLI
---
::

    python -m tools.checks.check_hardcoded_prompts                # warn-only
    python -m tools.checks.check_hardcoded_prompts --strict       # exit=1 если есть findings
    python -m tools.checks.check_hardcoded_prompts --min-length 80
    python -m tools.checks.check_hardcoded_prompts --root src/backend/services/ai

Выходные коды:
    0 — нет нарушений (или warn-only режим);
    1 — обнаружены нарушения и ``--strict``.
"""

from __future__ import annotations

import argparse
import ast
import fnmatch
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

__all__ = (
    "PROMPT_KWARGS",
    "PROMPT_BUILDER_CALLS",
    "Finding",
    "scan_file",
    "scan_paths",
    "main",
)

PROMPT_KWARGS: frozenset[str] = frozenset(
    {
        "system_prompt",
        "system_message",
        "system",
        "user_message",
        "user_prompt",
        "prompt",
        "instructions",
        "template",
        "messages",
        "content",
    }
)
"""Ключевые слова kwargs, в которых литералы > min_length считаются prompt-ами."""

PROMPT_BUILDER_CALLS: frozenset[str] = frozenset(
    {
        "SystemMessage",
        "HumanMessage",
        "AIMessage",
        "from_template",
        "from_messages",
        "PromptTemplate",
        "ChatPromptTemplate",
    }
)
"""Имена функций/конструкторов, у которых позиционные аргументы — это prompt."""

DEFAULT_EXCLUDES: tuple[str, ...] = (
    "**/tests/**",
    "**/test_*.py",
    "**/conftest.py",
    "**/fixtures/**",
    "**/__pycache__/**",
    "**/.venv/**",
    "**/node_modules/**",
    "**/migrations/**",
    "**/colang_flows/**",
)


@dataclass(slots=True, frozen=True)
class Finding:
    """Одно нарушение."""

    path: Path
    lineno: int
    col_offset: int
    kind: str
    where: str
    snippet: str

    def format(self) -> str:
        """``path:line:col: [kind] where — snippet``."""
        path_str = str(self.path)
        snippet = self.snippet
        if len(snippet) > 80:
            snippet = snippet[:77] + "..."
        return (
            f"{path_str}:{self.lineno}:{self.col_offset}: "
            f"[{self.kind}] {self.where} — {snippet!r}"
        )


def _const_str_value(node: ast.AST) -> str | None:
    """Вернуть строковое значение, если node — литеральная строка.

    Обрабатывает:
        * ``ast.Constant(value=str)``;
        * ``ast.JoinedStr`` без вычислений (только constant parts).
    """
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    if isinstance(node, ast.JoinedStr):
        parts: list[str] = []
        for v in node.values:
            if isinstance(v, ast.Constant) and isinstance(v.value, str):
                parts.append(v.value)
            elif isinstance(v, ast.FormattedValue):
                parts.append("{…}")
            else:
                return None
        return "".join(parts)
    return None


def _call_name(call: ast.Call) -> str | None:
    """Извлечь имя вызова (последний компонент атрибута или Name)."""
    func = call.func
    if isinstance(func, ast.Name):
        return func.id
    if isinstance(func, ast.Attribute):
        return func.attr
    return None


def _walk_calls(tree: ast.AST) -> Iterable[ast.Call]:
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            yield node


def _check_kwarg_findings(call: ast.Call, path: Path, min_length: int) -> list[Finding]:
    out: list[Finding] = []
    for kw in call.keywords:
        if kw.arg is None or kw.arg not in PROMPT_KWARGS:
            continue
        value = _const_str_value(kw.value)
        if value is None:
            continue
        if len(value) < min_length:
            continue
        out.append(
            Finding(
                path=path,
                lineno=kw.value.lineno,
                col_offset=kw.value.col_offset,
                kind="hardcoded-prompt-kwarg",
                where=f"kwarg `{kw.arg}` в вызове",
                snippet=value,
            )
        )
    return out


def _check_builder_findings(
    call: ast.Call, path: Path, min_length: int
) -> list[Finding]:
    name = _call_name(call)
    if name is None or name not in PROMPT_BUILDER_CALLS:
        return []
    out: list[Finding] = []
    for idx, arg in enumerate(call.args):
        value = _const_str_value(arg)
        if value is None or len(value) < min_length:
            continue
        out.append(
            Finding(
                path=path,
                lineno=arg.lineno,
                col_offset=arg.col_offset,
                kind="hardcoded-prompt-positional",
                where=f"позиционный arg #{idx} в {name}()",
                snippet=value,
            )
        )
    return out


def scan_file(path: Path, *, min_length: int = 50) -> list[Finding]:
    """Сканировать один Python-файл."""
    try:
        source = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return []
    try:
        tree = ast.parse(source, filename=str(path))
    except SyntaxError:
        return []

    findings: list[Finding] = []
    for call in _walk_calls(tree):
        findings.extend(_check_kwarg_findings(call, path, min_length))
        findings.extend(_check_builder_findings(call, path, min_length))
    return findings


def _load_allowlist(path: Path) -> list[str]:
    """Прочитать allowlist (glob-маски по одной на строку)."""
    if not path.exists():
        return []
    patterns: list[str] = []
    for raw in path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        patterns.append(line)
    return patterns


def _is_excluded(path: Path, patterns: Iterable[str], root: Path) -> bool:
    """Проверить, попадает ли файл под одну из glob-масок.

    ``Path.match`` поддерживает рекурсивный ``**``, fnmatch — нет.
    Проверяем сначала relative-path (стабильный для рантайма), затем
    отдельные компоненты пути по простым именам (директория ``tests`` и т.п.).
    """
    try:
        rel = path.relative_to(root)
    except ValueError:
        rel = path
    parts = set(path.parts)
    for pat in patterns:
        # Стандартные glob-маски на относительный путь.
        try:
            if rel.match(pat):
                return True
        except ValueError:
            pass
        # Поиск компонент: `**/tests/**` → ``tests``.
        bare = pat.strip("*/")
        if bare and "/" not in bare and "*" not in bare and bare in parts:
            return True
        # Шаблон вида ``**/test_*.py`` → проверяем только имя файла.
        if pat.startswith("**/") and fnmatch.fnmatch(path.name, pat[3:]):
            return True
    return False


def scan_paths(
    roots: Iterable[Path],
    *,
    min_length: int = 50,
    excludes: Iterable[str] = DEFAULT_EXCLUDES,
    allowlist: Iterable[str] = (),
) -> list[Finding]:
    """Рекурсивный обход директорий + сбор findings."""
    all_excludes = list(excludes) + list(allowlist)
    out: list[Finding] = []
    for root in roots:
        if root.is_file() and root.suffix == ".py":
            if _is_excluded(root, all_excludes, root.parent):
                continue
            out.extend(scan_file(root, min_length=min_length))
            continue
        if not root.is_dir():
            continue
        for path in root.rglob("*.py"):
            if _is_excluded(path, all_excludes, root):
                continue
            out.extend(scan_file(path, min_length=min_length))
    return out


def main(argv: list[str] | None = None) -> int:
    """CLI entry-point."""
    parser = argparse.ArgumentParser(description="AST-checker hardcoded LLM-prompts")
    parser.add_argument(
        "--root",
        type=Path,
        action="append",
        default=None,
        help="Корень сканирования (можно указать несколько раз). "
        "По умолчанию: src/backend/services/ai",
    )
    parser.add_argument(
        "--min-length",
        type=int,
        default=50,
        help="Минимальная длина строки для триггера (default: 50)",
    )
    parser.add_argument(
        "--allowlist",
        type=Path,
        default=Path("tools/checks/prompt_allowlist.txt"),
        help="Файл с glob-масками исключений",
    )
    parser.add_argument(
        "--strict", action="store_true", help="exit=1 при наличии findings"
    )
    parser.add_argument(
        "--quiet", action="store_true", help="Печатать только итоговое количество"
    )
    args = parser.parse_args(argv)

    roots: list[Path] = args.root or [Path("src/backend/services/ai")]
    allowlist = _load_allowlist(args.allowlist)
    findings = scan_paths(roots, min_length=args.min_length, allowlist=allowlist)

    if not args.quiet:
        for f in findings:
            print(f.format())

    total = len(findings)
    if total == 0:
        print("[check-hardcoded-prompts] OK: hardcoded prompts не найдены")
        return 0

    print(
        f"[check-hardcoded-prompts] FOUND {total} hardcoded prompts "
        f"(min-length={args.min_length})",
        file=sys.stderr,
    )
    if args.strict:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
