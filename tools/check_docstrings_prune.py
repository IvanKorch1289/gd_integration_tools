#!/usr/bin/env python3
"""Pruner для allowlist stale entries — cycle 34.

Allowlist в ``tools/check_docstrings_allowlist.txt`` (1372+ entries)
накапливает stale entries:
- **Deleted files**: файл переименован/удалён, entry указывает на
  несуществующий path.
- **No-longer-missing**: entry был добавлен как baseline, но
  docstring уже написан (или удалён целевой symbol). Entry
  больше не покрывает никакой violation → dead weight.

Без prune'a allowlist растёт монотонно (cycle 31 Agent 87 audit:
  80% stale rate из-за cycle-30 recursive methods visit +
  cycle-22-batch2 swarm merges). Каждый refactor добавляет
  drift, делает allowlist всё менее полезным как reference.

**Использование**:

    # Dry-run: показать, что было бы удалено (без изменений)
    uv run python tools/check_docstrings_prune.py \\
        --allowlist tools/check_docstrings_allowlist.txt \\
        src/backend/...

    # Применить prune
    uv run python tools/check_docstrings_prune.py \\
        --allowlist tools/check_docstrings_allowlist.txt \\
        --write \\
        src/backend/...

Honest scope: prune ТОЛЬКО entries с deleted-file или no-longer-missing
(т.е. docstring уже есть). Heuristic-based — line-number drift остаётся
fundamental problem (см. CLAUDE.md allowlist drift discussion). Для
full correctness нужен AST-based matcher с qualified-name tracking,
что выходит за scope этого tool.

Возвращает:
- ``--dry-run`` (default): exit 0, prints stats, file unchanged.
- ``--write``: writes trimmed allowlist; exit 0 если entries удалены,
  exit 1 если ни одной entry не удалено (no-op).

Cycle 34: initial release. Покрыто 6 unit-тестами в
``tests/unit/tools/test_check_docstrings_prune.py``.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

# Импортируем helpers из основного check_docstrings.py.
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from tools.check_docstrings import (  # noqa: E402
    load_allowlist,
    scan_paths,
)


def parse_entry(entry: str) -> tuple[str, int, str] | None:
    """Парсит ``<path>:<lineno>:<col> <qualified_name>`` в tuple.

    Returns ``(path, lineno, qualified_name)`` или ``None`` если строка
    не в ожидаемом формате.
    """
    parts = entry.split(":", 2)
    if len(parts) < 3:
        return None
    path = parts[0]
    try:
        lineno = int(parts[1])
    except ValueError:
        return None
    # parts[2] = "<col> <qualified_name>" → берём последний whitespace-token.
    rest = parts[2].strip()
    qname = rest.split()[-1] if rest else ""
    if not qname:
        return None
    return (path, lineno, qname)


def collect_current_violations(
    paths: list[Path],
    *,
    enable_module_check: bool = False,
) -> set[tuple[str, int, str]]:
    """Сканирует paths и возвращает set ``(path, lineno, name)`` для
    всех найденных missing docstrings.

    Note: имя используется как bare (short) name, не qualified — этого
    достаточно для matching с allowlist (allowlist matcher использует
    ``rsplit('.', 1)[-1]`` тоже).
    """
    if not paths:
        return set()
    all_stats, _ = scan_paths(paths, enable_module_check=enable_module_check)
    violations: set[tuple[str, int, str]] = set()
    for stats in all_stats:
        rel_path = str(stats.path)
        for issue in stats.issues:
            violations.add((rel_path, issue.line, issue.name))
    return violations


def find_stale_entries(
    allowlist_entries: set[str],
    current_paths: list[Path],
    *,
    enable_module_check: bool = False,
) -> tuple[set[str], set[str], set[str]]:
    """Классифицирует allowlist entries на keep / deleted-file / no-longer-missing.

    Returns:
        ``(keep, deleted, obsolete)`` — три множества строк entries:
        - ``keep``: entry актуальна (path exists AND match current violation)
        - ``deleted``: path не существует
        - ``obsolete``: path exists, но entry не покрывает никакой violation
          (docstring уже написан ИЛИ symbol удалён, но файл ещё есть)
    """
    current_violations = collect_current_violations(
        current_paths, enable_module_check=enable_module_check,
    )
    keep: set[str] = set()
    deleted: set[str] = set()
    obsolete: set[str] = set()
    for entry in allowlist_entries:
        parsed = parse_entry(entry)
        if parsed is None:
            # Malformed — оставляем как есть (не трогаем legacy data).
            keep.add(entry)
            continue
        path, lineno, qname = parsed
        if not Path(path).exists():
            deleted.add(entry)
            continue
        # Bare name match (allowlist matcher pattern).
        bare_name = qname.rsplit(".", 1)[-1]
        if (path, lineno, bare_name) in current_violations:
            keep.add(entry)
        else:
            obsolete.add(entry)
    return keep, deleted, obsolete


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Prune stale entries из docstring allowlist.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--allowlist",
        type=Path,
        required=True,
        help="Path to allowlist file.",
    )
    parser.add_argument(
        "--write",
        action="store_true",
        help="Apply changes (default: dry-run, only print stats).",
    )
    parser.add_argument(
        "paths",
        nargs="+",
        type=Path,
        help="Paths to scan for current violations.",
    )
    parser.add_argument(
        "--module-level",
        action="store_true",
        help="Also scan module-level docstrings (default: OFF).",
    )

    args = parser.parse_args()

    if not args.allowlist.is_file():
        print(f"Error: allowlist not found: {args.allowlist}", file=sys.stderr)
        return 2

    allowlist = load_allowlist(args.allowlist)
    keep, deleted, obsolete = find_stale_entries(
        allowlist, args.paths,
        enable_module_check=args.module_level,
    )
    stale = deleted | obsolete
    print(f"Total entries: {len(allowlist)}")
    print(f"  Keep (active):   {len(keep)}")
    print(f"  Deleted file:    {len(deleted)}")
    print(f"  Obsolete (no missing docstring): {len(obsolete)}")
    print(f"  Stale (would remove): {len(stale)}")

    if not args.write:
        print("\n(dry-run: pass --write to apply)")
        return 0

    if not stale:
        print("\nNothing to prune.")
        return 1  # No-op (matches ``git status`` semantics)

    # Rewrite allowlist: keep header comments + keep entries.
    with args.allowlist.open(encoding="utf-8") as f:
        original_lines = f.readlines()
    keep_lines = [
        line for line in original_lines
        if line.strip() in keep
        or line.strip().startswith("#")
        or not line.strip()
    ]
    args.allowlist.write_text("".join(keep_lines), encoding="utf-8")
    print(f"\nWrote {args.allowlist} (removed {len(stale)} stale entries).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
