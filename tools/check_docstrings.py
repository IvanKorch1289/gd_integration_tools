#!/usr/bin/env python3
"""
Docstring coverage analyzer for Python codebases.

Scans Python files for public functions/classes without docstrings.
Supports --summary, --path, and --json output modes.
"""

from __future__ import annotations

import ast
import argparse
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterator


@dataclass
class MissingDocstring:
    """Record of a public function/class missing its docstring."""
    file: Path
    line: int
    name: str
    kind: str  # 'function' | 'class' | 'module'
    signature: str = ""


@dataclass
class FileStats:
    """Statistics for a single file."""
    path: Path
    documented: int = 0
    missing: int = 0
    issues: list[MissingDocstring] = field(default_factory=list)


@dataclass
class AggregateStats:
    """Aggregate statistics across all files."""
    total_files: int = 0
    total_documented: int = 0
    total_missing: int = 0
    files_with_issues: int = 0


class DocstringVisitor(ast.NodeVisitor):
    """AST visitor that finds public functions/classes without docstrings."""

    def __init__(
        self,
        filepath: Path,
        *,
        enable_module_check: bool = False,
    ) -> None:
        self.filepath = filepath
        self.issues: list[MissingDocstring] = []
        self._in_class_stack: list[str] = []
        self.enable_module_check = enable_module_check

    def _is_public(self, name: str) -> bool:
        """Check if name represents a public definition (not starting with _)."""
        return not name.startswith('_')

    def _get_signature(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> str:
        """Extract function signature as string.

        Cycle 30 fix: оригинал использовал ``args.args[len(args.args):]``
        — пустой slice, regular args выпадали из signature. Теперь явно
        пропускаем ``self/cls`` (если это instance/class method) и
        добавляем все regular args, defaults, *args, kwonly, **kwargs.
        """
        args = node.args
        parts: list[str] = []

        # Пропускаем self/cls (первый positional arg в методах).
        # Heuristic: если первый arg называется self/cls — это метод.
        # Для top-level functions первый arg — обычный параметр.
        regular_args = list(args.args)
        is_method = bool(regular_args and regular_args[0].arg in ("self", "cls"))
        if is_method:
            regular_args = regular_args[1:]

        # Positional-only (Python 3.8+): /  до первого / .
        posonly = list(args.posonlyargs)
        # Regular args (после /)
        for arg in regular_args:
            parts.append(arg.arg)

        # Defaults применяются к последним N regular args.
        # Defaults размещены в конце args.args ИЛИ в конце posonlyargs.
        # Простой случай: defaults привязаны к args.args (most common).
        defaults_offset = len(args.args) - len(args.defaults)
        for i, default in enumerate(args.defaults):
            arg_name = args.args[defaults_offset + i].arg
            if isinstance(default, ast.Constant):
                default_val = repr(default.value)
            elif isinstance(default, ast.Name):
                default_val = default.id
            elif isinstance(default, ast.Attribute):
                default_val = ast.unparse(default)
            elif isinstance(default, (ast.List, ast.Tuple, ast.Dict, ast.Set)):
                default_val = ast.unparse(default)
            else:
                default_val = "..."
            parts.append(f"{arg_name}={default_val}")

        # *args
        if args.vararg:
            parts.append(f"*{args.vararg.arg}")

        # Keyword-only (после * или *args)
        # kw_defaults — список длиной len(kwonlyargs); None = default required.
        for i, arg in enumerate(args.kwonlyargs):
            default_node = args.kw_defaults[i] if i < len(args.kw_defaults) else None
            if default_node is None:
                parts.append(arg.arg)
            elif isinstance(default_node, ast.Constant):
                parts.append(f"{arg.arg}={default_node.value!r}")
            else:
                parts.append(f"{arg.arg}={ast.unparse(default_node)}")

        # **kwargs
        if args.kwarg:
            parts.append(f"**{args.kwarg.arg}")

        # Return type hint
        prefix = "async def " if isinstance(node, ast.AsyncFunctionDef) else "def "
        if node.returns:
            ret = ast.unparse(node.returns)
            return f"{prefix}{node.name}({', '.join(parts)}) -> {ret}"
        return f"{prefix}{node.name}({', '.join(parts)})"

    def _check_function(
        self, node: ast.FunctionDef | ast.AsyncFunctionDef
    ) -> None:
        """Check if a function needs a docstring."""
        if not self._is_public(node.name):
            return

        # Skip private methods
        if node.name.startswith('_'):
            return

        # Skip __init__ ONLY if body is exactly ``super().__init__()``
        # (with optional ``pass``). Cycle 30 fix: оригинал использовал
        # ``isinstance(stmt, ast.Expr)`` который матчил ЛЮБОЕ выражение,
        # не только super().__init__().
        if node.name == '__init__':
            if self._is_trivial_init(node):
                return

        # Check for docstring
        if not ast.get_docstring(node):
            self.issues.append(MissingDocstring(
                file=self.filepath,
                line=node.lineno or 0,
                name=node.name,
                kind='function',
                signature=self._get_signature(node),
            ))

    def _is_trivial_init(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> bool:
        """True если __init__ содержит ТОЛЬКО super().__init__() (± pass)."""
        body = node.body
        # Допускаем первую stmt = docstring (skip), далее super call + pass.
        stmts = [s for s in body if not (
            isinstance(s, ast.Expr) and isinstance(s.value, ast.Constant)
            and isinstance(s.value.value, str)
        )]
        # Допустимые формы: [] (пустой), [Pass], [super().__init__()], [super().__init__(), Pass]
        if all(isinstance(s, ast.Pass) for s in stmts):
            return True
        if len(stmts) == 1:
            s = stmts[0]
            if (isinstance(s, ast.Expr)
                    and isinstance(s.value, ast.Call)
                    and isinstance(s.value.func, ast.Attribute)
                    and s.value.func.attr == '__init__'):
                return True
        return False

    def _check_class(self, node: ast.ClassDef) -> None:
        """Check if a class needs a docstring.

        Cycle 30 fix: оригинал НЕ вызывал generic_visit, поэтому
        методы классов не посещались. ``visit_FunctionDef`` /
        ``visit_AsyncFunctionDef`` срабатывали только на module-level
        functions. Теперь рекурсивно обходим тело класса.
        """
        if not self._is_public(node.name):
            return

        if not ast.get_docstring(node):
            self.issues.append(MissingDocstring(
                file=self.filepath,
                line=node.lineno or 0,
                name=node.name,
                kind='class',
                signature=f"class {node.name}",
            ))
        # Visit class body для методов (Cycle 30 fix).
        self.generic_visit(node)

    def _check_module_docstring(self, tree: ast.Module) -> None:
        """Cycle 32 (M12): опциональная проверка module-level docstring.

        По умолчанию ВЫКЛЮЧЕНА (через ``enable_module_check``). Включается
        CLI флагом ``--module-level``. Не все модули требуют docstring
        (e.g. ``__init__.py`` re-exports, простые протоколы), поэтому
        opt-in — чтобы gate оставался green для legacy.
        """
        if not self.enable_module_check:
            return
        if ast.get_docstring(tree):
            return
        # Skip __init__.py — обычно re-exports, docstring не нужен.
        if self.filepath.name == "__init__.py":
            return
        # Skip empty / trivial modules (≤2 non-docstring stmts).
        non_docstring_stmts = [
            s for s in tree.body
            if not (
                isinstance(s, ast.Expr)
                and isinstance(s.value, ast.Constant)
                and isinstance(s.value.value, str)
            )
        ]
        if len(non_docstring_stmts) <= 2:
            return
        self.issues.append(MissingDocstring(
            file=self.filepath,
            line=1,
            name="<module>",
            kind='module',
            signature="module",
        ))

    visit_FunctionDef = _check_function
    visit_AsyncFunctionDef = _check_function
    visit_ClassDef = _check_class


def scan_file(filepath: Path, *, enable_module_check: bool = False) -> FileStats:
    """Scan a single Python file for missing docstrings.

    Cycle 32: ``enable_module_check`` (default False) — также проверяет
    наличие module-level docstring. Не все модули требуют его, поэтому
    opt-in. Активируется CLI флагом ``--module-level``.
    """
    stats = FileStats(path=filepath)

    try:
        content = filepath.read_text(encoding='utf-8')
        tree = ast.parse(content, filename=str(filepath))
    except (SyntaxError, UnicodeDecodeError) as e:
        print(f"Warning: skipping {filepath}: {e}", file=sys.stderr)
        return stats

    visitor = DocstringVisitor(
        filepath,
        enable_module_check=enable_module_check,
    )
    visitor.visit(tree)
    # Module-level check (cycle 32) — отдельная проверка после обхода.
    visitor._check_module_docstring(tree)

    for issue in visitor.issues:
        stats.issues.append(issue)
        stats.missing += 1

    if visitor.issues:
        stats.files_with_issues = 1

    return stats


def scan_directory(root: Path) -> Iterator[Path]:
    """Yield all .py files in directory, excluding __pycache__."""
    for path in root.rglob('*.py'):
        if '__pycache__' not in path.parts:
            yield path


def scan_paths(
    paths: list[Path],
    *,
    enable_module_check: bool = False,
) -> tuple[list[FileStats], AggregateStats]:
    """Scan multiple paths and return stats."""
    all_stats: list[FileStats] = []
    aggregate = AggregateStats()

    for path in paths:
        if path.is_file():
            all_stats.append(scan_file(
                path, enable_module_check=enable_module_check,
            ))
        elif path.is_dir():
            for py_file in scan_directory(path):
                all_stats.append(scan_file(
                    py_file, enable_module_check=enable_module_check,
                ))

    # Compute aggregate
    for stats in all_stats:
        if stats.issues:
            aggregate.files_with_issues += 1
        aggregate.total_missing += stats.missing

    aggregate.total_files = len(all_stats)

    return all_stats, aggregate


def format_output(
    all_stats: list[FileStats],
    aggregate: AggregateStats,
    json_format: bool = False,
    summary_only: bool = False,
) -> str:
    """Format output in text or JSON format."""
    if json_format:
        return json_format_output(all_stats, aggregate)

    lines: list[str] = []

    if not summary_only:
        for stats in all_stats:
            for issue in stats.issues:
                lines.append(
                    f"{issue.file}:{issue.line} - "
                    f"Missing docstring: {issue.signature}"
                )

    # Summary
    total_issues = aggregate.total_missing
    files_count = aggregate.files_with_issues

    lines.append(f"Total: {total_issues} missing docstrings in {files_count} file{'s' if files_count != 1 else ''}")

    # Calculate coverage percentage
    # Estimate documented count from issues + files
    # This is approximate since we don't know total symbols
    if total_issues > 0:
        # Show raw numbers since we can't know total without full scan
        lines.append(f"Files scanned: {aggregate.total_files}")
    else:
        lines.append(f"Files scanned: {aggregate.total_files}")

    return '\n'.join(lines)


def json_format_output(
    all_stats: list[FileStats],
    aggregate: AggregateStats,
) -> str:
    """Format output as JSON."""
    result = {
        'summary': {
            'total_files': aggregate.total_files,
            'files_with_issues': aggregate.files_with_issues,
            'total_missing': aggregate.total_missing,
        },
        'files': [],
    }

    for stats in all_stats:
        if not stats.issues:
            continue
        result['files'].append({
            'path': str(stats.path),
            'issues': [
                {
                    'line': issue.line,
                    'name': issue.name,
                    'kind': issue.kind,
                    'signature': issue.signature,
                }
                for issue in stats.issues
            ],
        })

    return json.dumps(result, indent=2)


def load_allowlist(path: Path) -> set[str]:
    """Load allowlist из file.

    Формат allowlist: одна запись на строку, ``<path>:<lineno>:<col> <qualified_name>``.
    Пустые строки и комментарии (начинающиеся с ``#``) игнорируются.
    Возвращает set точных строк для O(1) lookup.
    """
    entries: set[str] = set()
    if not path.is_file():
        return entries
    for line in path.read_text(encoding='utf-8').splitlines():
        stripped = line.strip()
        if stripped and not stripped.startswith('#'):
            entries.add(stripped)
    return entries


def main() -> int:
    parser = argparse.ArgumentParser(
        description='Check for missing docstrings in Python code.',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog='''
Examples:
  %(prog)s src/                          # Scan src directory
  %(prog)s src/backend/core/config/      # Scan specific directory
  %(prog)s --summary src/                # Summary only
  %(prog)s --json src/ > report.json     # JSON output
  %(prog)s --allowlist tools/check_docstrings_allowlist.txt \\
      src/backend/core                   # Skip allowlisted entries
  %(prog)s --module-level src/backend/    # Also check module docstrings
        ''',
    )
    parser.add_argument(
        'paths',
        nargs='*',
        type=Path,
        default=[Path('src')],
        help='Paths to scan (default: src)',
    )
    parser.add_argument(
        '--summary',
        action='store_true',
        help='Show only summary statistics',
    )
    parser.add_argument(
        '--json',
        action='store_true',
        help='Output in JSON format',
    )
    parser.add_argument(
        '--allowlist',
        type=Path,
        default=None,
        help='Path to allowlist file (skip listed entries)',
    )
    parser.add_argument(
        '--module-level',
        action='store_true',
        help='Also check module-level docstrings (default: OFF, opt-in)',
    )

    args = parser.parse_args()

    all_stats, aggregate = scan_paths(
        args.paths, enable_module_check=args.module_level,
    )

    # Filter out allowlisted entries
    if args.allowlist is not None:
        allowlist = load_allowlist(args.allowlist)
        if allowlist:
            # Index allowlist by (rel_path, lineno) → set of qualified_names
            # so we can match both ``MethodName`` and ``ClassName.MethodName``.
            allowlist_by_loc: dict[tuple[str, int], set[str]] = {}
            for entry in allowlist:
                # entry: ``<rel_path>:<lineno>:<col> <qualified_name>``
                # Split on first 3 colons, then whitespace separates col from name.
                parts = entry.split(":", 2)
                if len(parts) < 3:
                    continue
                p, ln, rest = parts[0], int(parts[1]), parts[2].strip()
                # ``rest`` is ``<col> <qualified_name>`` (e.g. ``0 AuthMethod``
                # or ``4 AuditBackend.emit``). Take the last whitespace-separated
                # token as the qualified name.
                qname = rest.split()[-1] if rest else ""
                # qname может быть ``Foo.method`` или ``top_level_func``
                bare = qname.rsplit(".", 1)[-1]
                if not bare:
                    continue
                allowlist_by_loc.setdefault((p, ln), set()).add(bare)
            for stats in all_stats:
                rel_path = str(stats.path)
                filtered_issues = []
                for issue in stats.issues:
                    bare_names = allowlist_by_loc.get((rel_path, issue.line), set())
                    if issue.name in bare_names:
                        # Skip: covered by allowlist (either top-level or class member).
                        continue
                    filtered_issues.append(issue)
                stats.issues = filtered_issues
                stats.missing = len(filtered_issues)
            # Recompute aggregate after filter
            aggregate.total_missing = sum(s.missing for s in all_stats)
            aggregate.files_with_issues = sum(1 for s in all_stats if s.issues)

    output = format_output(
        all_stats,
        aggregate,
        json_format=args.json,
        summary_only=args.summary,
    )

    print(output)

    # Exit code 1 if there are issues
    return 1 if aggregate.total_missing > 0 else 0


if __name__ == '__main__':
    sys.exit(main())
