"""AST-gate: запрет новых импортов ``src.backend.dsl.processors`` (v6 / 25.09 audit).

Legacy ``src/backend/dsl/processors/`` — это compat shim branch (ADR-0313/0314)
с deprecation warnings. Все 24 файла там — re-export shims или SEMANTIC_KEEP
(saga_lra_processor). Per очерёдность W4: «Добавить AST-gate, запрещающий
новые импорты src.backend.dsl.processors».

Gate policy:
- Новые импорты ``from src.backend.dsl.processors.*`` или
  ``import src.backend.dsl.processors.*`` запрещены.
- Разрешены только через LEGACY_ALLOWLIST (3 legacy mixin в
  ``src/backend/dsl/builders/base/__init__.py``: plan_execute,
  reflection_loop, router_specialist — Sprint 7 миграция).
- Gate exit 1 если найдены запрещённые импорты вне allowlist.

Использование::

    python tools/checks/check_dsl_processors_imports.py            # human-readable
    python tools/checks/check_dsl_processors_imports.py --strict   # exit 1 на violations
    python tools/checks/check_dsl_processors_imports.py --json     # machine output

Migration target: ``src/backend/dsl/engine/processors/<name>.py``.
"""

from __future__ import annotations

import argparse
import ast
import json
import sys
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SRC_ROOT = PROJECT_ROOT / "src"
LEGACY_MODULE = "src.backend.dsl.processors"

# Per v6 W4 + 25.09 audit: 3 legacy mixin мигрированы в canonical
# (dsl/engine/processors/*) — allowlist обнулён. AST-gate теперь
# запрещает ВСЕ импорты src.backend.dsl.processors.* вне legacy branch.
LEGACY_ALLOWLIST: frozenset[tuple[str, int]] = frozenset()


@dataclass(frozen=True)
class Violation:
    """Одно нарушение AST-gate."""

    file: str
    line: int
    snippet: str
    module: str


def _iter_python_files() -> list[Path]:
    """Все .py в src/ исключая сам legacy branch (internal cross-imports)."""
    files: list[Path] = []
    for py in SRC_ROOT.rglob("*.py"):
        if "__pycache__" in py.parts:
            continue
        rel = py.relative_to(PROJECT_ROOT)
        rel_str = str(rel)
        # Skip сам legacy branch — внутренние cross-imports не считаются.
        if rel_str.startswith("src/backend/dsl/processors/"):
            continue
        files.append(py)
    return files


def _find_legacy_imports(py: Path) -> list[Violation]:
    """AST walk: находим все импорты ``src.backend.dsl.processors.*``.

    Возвращает список Violation для всех import statements, не в allowlist.
    """
    # v6 W4 robustness: resolve path → absolute → relative_to PROJECT_ROOT.
    # Без этого relative cwd path → ValueError → silent return [] (miss violations).
    abs_py = py if py.is_absolute() else py.resolve()
    try:
        tree = ast.parse(abs_py.read_text(encoding="utf-8", errors="ignore"))
    except SyntaxError:
        return []

    try:
        rel = str(abs_py.relative_to(PROJECT_ROOT))
    except ValueError:
        # Path не внутри project root — пропускаем.
        return []

    out: list[Violation] = []

    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            module = node.module or ""
            if module == LEGACY_MODULE or module.startswith(LEGACY_MODULE + "."):
                snippet = ast.unparse(node).split("\n")[0][:120]
                key = (rel, node.lineno)
                if key in LEGACY_ALLOWLIST:
                    continue
                out.append(
                    Violation(
                        file=rel,
                        line=node.lineno,
                        snippet=snippet,
                        module=module,
                    )
                )
        elif isinstance(node, ast.Import):
            # `import src.backend.dsl.processors.X` — крайне редко, но проверим.
            for alias in node.names:
                name = alias.name
                if name == LEGACY_MODULE or name.startswith(LEGACY_MODULE + "."):
                    snippet = ast.unparse(node).split("\n")[0][:120]
                    key = (rel, node.lineno)
                    if key in LEGACY_ALLOWLIST:
                        continue
                    out.append(
                        Violation(
                            file=rel,
                            line=node.lineno,
                            snippet=snippet,
                            module=name,
                        )
                    )
    return out


def build_violations() -> list[Violation]:
    """Сканировать все .py файлы вне legacy branch."""
    out: list[Violation] = []
    for py in _iter_python_files():
        out.extend(_find_legacy_imports(py))
    return out


def render_table(violations: list[Violation]) -> str:
    """Human-readable table."""
    if not violations:
        return (
            "✅ AST-gate: no new imports of legacy "
            "src.backend.dsl.processors outside allowlist.\n"
        )
    lines = [
        f"AST-gate violations: {len(violations)} new imports of "
        f"{LEGACY_MODULE}.* outside allowlist.",
        "",
        f"{'File':<60} {'Line':>5}  {'Module':<45}",
        "-" * 130,
    ]
    for v in violations:
        lines.append(
            f"{v.file:<60} {v.line:>5}  {v.module:<45}"
        )
    lines.append("")
    lines.append(
        f"Migration target: ``{LEGACY_MODULE.replace('src.backend.', '')}``"
        f" → ``dsl.engine.processors.<name>``."
    )
    lines.append(
        "Allowlist: 3 lines in src/backend/dsl/builders/base/__init__.py "
        "(PlanExecute, ReflectionLoop, RouterSpecialist mixin) — Sprint 7 migration."
    )
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "AST-gate: запрет новых импортов "
            "src.backend.dsl.processors (legacy compat branch)."
        )
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Exit 1 если есть violations (CI gate per v6 W4).",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Machine-readable JSON output.",
    )
    args = parser.parse_args(argv)

    violations = build_violations()

    if args.json:
        payload = {
            "generated_at": datetime.now(UTC).isoformat(),
            "legacy_module": LEGACY_MODULE,
            "allowlist_size": len(LEGACY_ALLOWLIST),
            "violations_count": len(violations),
            "violations": [asdict(v) for v in violations],
        }
        sys.stdout.write(json.dumps(payload, ensure_ascii=False, indent=2) + "\n")
    else:
        sys.stdout.write(render_table(violations) + "\n")

    if args.strict and violations:
        sys.stderr.write(
            f"\nAST-gate FAILED: {len(violations)} new imports of legacy "
            f"{LEGACY_MODULE}.* outside allowlist. Migrate to "
            f"src.backend.dsl.engine.processors.<name>.\n"
        )
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
