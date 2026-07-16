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
    kind: str  # 'function' or 'class'
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

    def __init__(self, filepath: Path) -> None:
        self.filepath = filepath
        self.issues: list[MissingDocstring] = []
        self._in_class_stack: list[str] = []

    def _is_public(self, name: str) -> bool:
        """Check if name represents a public definition (not starting with _)."""
        return not name.startswith('_')

    def _get_signature(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> str:
        """Extract function signature as string."""
        args = node.args
        parts: list[str] = []

        # Self/cls parameter
        if args.args:
            parts.append(args.args[0].arg)

        # Regular args
        for arg in args.args[len(args.args) if args.args else 0:]:
            parts.append(arg.arg)

        # *args
        if args.vararg:
            parts.append(f"*{args.vararg.arg}")

        # Keyword args with defaults
        defaults_offset = len(args.args) - len(args.defaults)
        for i, default in enumerate(args.defaults):
            arg_name = args.args[defaults_offset + i].arg
            if isinstance(default, ast.Constant):
                default_val = repr(default.value)
            elif isinstance(default, ast.Name):
                default_val = default.id
            else:
                default_val = "..."
            parts.append(f"{arg_name}={default_val}")

        # **kwargs
        if args.kwarg:
            parts.append(f"**{args.kwarg.arg}")

        # Return type hint
        if node.returns:
            ret = ast.unparse(node.returns)
            return f"def {node.name}({', '.join(parts)}) -> {ret}"
        return f"def {node.name}({', '.join(parts)})"

    def _check_function(
        self, node: ast.FunctionDef | ast.AsyncFunctionDef
    ) -> None:
        """Check if a function needs a docstring."""
        if not self._is_public(node.name):
            return

        # Skip private methods
        if node.name.startswith('_'):
            return

        # Skip __init__ if it just calls super().__init__ (common pattern)
        if node.name == '__init__':
            # Simple heuristic: if only pass or super call, skip
            has_only_super = (
                len(node.body) <= 2
                and any(
                    isinstance(stmt, (ast.Expr, ast.Pass))
                    or (
                        isinstance(stmt, ast.Expr)
                        and isinstance(stmt.value, ast.Call)
                        and isinstance(stmt.value.func, ast.Attribute)
                        and stmt.value.func.attr == '__init__'
                    )
                    for stmt in node.body
                )
            )
            if has_only_super:
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

    def _check_class(self, node: ast.ClassDef) -> None:
        """Check if a class needs a docstring."""
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

    visit_FunctionDef = _check_function
    visit_AsyncFunctionDef = _check_function
    visit_ClassDef = _check_class


def scan_file(filepath: Path) -> FileStats:
    """Scan a single Python file for missing docstrings."""
    stats = FileStats(path=filepath)

    try:
        content = filepath.read_text(encoding='utf-8')
        tree = ast.parse(content, filename=str(filepath))
    except (SyntaxError, UnicodeDecodeError) as e:
        print(f"Warning: skipping {filepath}: {e}", file=sys.stderr)
        return stats

    visitor = DocstringVisitor(filepath)
    visitor.visit(tree)

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


def scan_paths(paths: list[Path]) -> tuple[list[FileStats], AggregateStats]:
    """Scan multiple paths and return stats."""
    all_stats: list[FileStats] = []
    aggregate = AggregateStats()

    for path in paths:
        if path.is_file():
            all_stats.append(scan_file(path))
        elif path.is_dir():
            for py_file in scan_directory(path):
                all_stats.append(scan_file(py_file))

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

    args = parser.parse_args()

    all_stats, aggregate = scan_paths(args.paths)

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
