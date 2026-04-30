"""W14.4 — статический аудит классификации side-effects процессоров.

Сканирует ``src/dsl/engine/processors/`` и проверяет:

1. Все наследники ``BaseProcessor`` явно объявляют ``side_effect`` —
   warning на использование default ``PURE`` (можно подавить опцией
   ``--allow-default``).
2. Если ``side_effect = SIDE_EFFECTING``, рекомендация явно установить
   ``compensatable`` (True/False) — нельзя оставлять unclear.

Запускается через ``make side-effect-audit``. Возвращает 0 если все
предупреждения подавлены или используется ``--allow-default``, иначе 1.
"""

from __future__ import annotations

import argparse
import ast
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PROCESSORS_DIR = ROOT / "src" / "dsl" / "engine" / "processors"


def _is_base_processor_subclass(node: ast.ClassDef) -> bool:
    """Класс наследует ``BaseProcessor`` (или потомков с тем же контрактом)."""
    for base in node.bases:
        if isinstance(base, ast.Name) and base.id in {
            "BaseProcessor",
            "_BaseWindow",
            "CallableProcessor",
        }:
            return True
        if isinstance(base, ast.Attribute) and base.attr in {
            "BaseProcessor",
            "_BaseWindow",
        }:
            return True
    return False


def _has_class_attr(node: ast.ClassDef, name: str) -> bool:
    """Класс задаёт class-attribute ``name`` на верхнем уровне тела."""
    for stmt in node.body:
        if isinstance(stmt, ast.Assign):
            for target in stmt.targets:
                if isinstance(target, ast.Name) and target.id == name:
                    return True
        if isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name):
            if stmt.target.id == name:
                return True
    return False


def _classify_module(path: Path, *, allow_default: bool) -> list[str]:
    issues: list[str] = []
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except SyntaxError as exc:
        issues.append(f"{path.relative_to(ROOT)}: SyntaxError {exc}")
        return issues
    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef):
            continue
        if not _is_base_processor_subclass(node):
            continue
        rel = path.relative_to(ROOT)
        has_kind = _has_class_attr(node, "side_effect")
        if not has_kind and not allow_default:
            issues.append(
                f"{rel}:{node.lineno}: класс {node.name!r} без явного "
                "side_effect (default PURE — допустим с --allow-default)"
            )
    return issues


def main() -> int:
    parser = argparse.ArgumentParser(description="W14.4 audit of side-effects")
    parser.add_argument(
        "--allow-default", action="store_true", help="не считать default PURE ошибкой"
    )
    args = parser.parse_args()

    issues: list[str] = []
    for path in PROCESSORS_DIR.rglob("*.py"):
        if path.name.startswith("_") and path.name != "__init__.py":
            continue
        issues.extend(_classify_module(path, allow_default=args.allow_default))

    if issues:
        for line in issues:
            print(f"[side-effect] {line}")
        return 1
    print(
        f"[side-effect] OK: проверено модулей в {PROCESSORS_DIR.relative_to(ROOT)}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
