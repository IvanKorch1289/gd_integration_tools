"""Check feature flag dependencies — lint для *_strict flags без declared dependencies.

Назначение:
    Проверяет что все *_strict feature flags в features.py объявлены либо:
    - в ``_FEATURE_FLAG_DEPENDENCIES`` (WARNING-level);
    - в ``_FEATURE_FLAG_DEPENDENCIES_CRITICAL`` (CRITICAL-level);
    - с явным комментарием ``# no dependency required`` рядом с полем.

    Парсит features.py через AST и сверяет с validator.py константами.
    Соответствует S31 w1 Фаза D.

Использование:
    python tools/checks/check_feature_flag_dependencies.py
    python tools/checks/check_feature_flag_dependencies.py --strict   # blocking gate

Возвращает exit 0 если все strict flags покрыты, иначе exit 1.
"""

from __future__ import annotations

import ast
import re
import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
_VALIDATOR_PATH = _ROOT / "src/backend/core/config/validator.py"
_FEATURES_PATH = _ROOT / "src/backend/core/config/features.py"


def _parse_strict_flags(features_py: str) -> dict[str, int]:
    """Находит все Field(...) с именем *_strict в features.py. Возвращает name → lineno."""
    tree = ast.parse(features_py)
    strict_flags: dict[str, int] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and node.id.endswith("_strict"):
            strict_flags[node.id] = node.lineno
    return strict_flags


def _parse_declared_dependencies(validator_py: str) -> tuple[set[str], set[str]]:
    """Парсит validator.py и возвращает множества declared dependencies."""
    warning_deps = set()
    critical_deps = set()

    # WARNING dict keys
    warning_match = re.findall(
        r'_FEATURE_FLAG_DEPENDENCIES\s*=\s*\{[^}]*"([^"]+)":',
        validator_py,
        re.DOTALL,
    )
    for key in warning_match:
        warning_deps.add(key.strip())

    # CRITICAL dict keys
    critical_match = re.findall(
        r'_FEATURE_FLAG_DEPENDENCIES_CRITICAL\s*=\s*\{[^}]*"([^"]+)":',
        validator_py,
        re.DOTALL,
    )
    for key in critical_match:
        critical_deps.add(key.strip())

    return warning_deps, critical_deps


def _check_no_dep_required_comments(features_py: str) -> set[str]:
    """Находит strict flags с комментарием # no dependency required."""
    pattern = re.compile(
        r'^\s*(\w*_strict\w*)\s*:\s*[^#]*#.*no dependency required',
        re.MULTILINE,
    )
    return {m.group(1) for m in pattern.finditer(features_py)}


def run_check(strict_mode: bool = False) -> int:
    """Основная проверка. Возвращает 0 если всё покрыто, 1 если нарушения."""
    if not _VALIDATOR_PATH.exists():
        print(f"[ERROR] validator.py не найден: {_VALIDATOR_PATH}", file=sys.stderr)
        return 1
    if not _FEATURES_PATH.exists():
        print(f"[ERROR] features.py не найден: {_FEATURES_PATH}", file=sys.stderr)
        return 1

    validator_src = _VALIDATOR_PATH.read_text()
    features_src = _FEATURES_PATH.read_text()

    strict_flags = _parse_strict_flags(features_src)
    warning_deps, critical_deps = _parse_declared_dependencies(validator_src)
    no_dep_required = _check_no_dep_required_comments(features_src)

    all_declared = warning_deps | critical_deps | no_dep_required
    undeclared = [name for name in strict_flags if name not in all_declared]

    if not undeclared:
        print("[OK] Все *_strict flags объявлены в dependencies или have no-dep comment.")
        return 0

    print(f"[FAIL] {len(undeclared)} *_strict flag(s) без declared dependency:")
    for name in undeclared:
        print(f"  - {name} (строка ~{strict_flags[name]})")
    print()
    print("  Решения:")
    print("    1. Добавить пару в _FEATURE_FLAG_DEPENDENCIES (WARNING) в validator.py:")
    print(f'       "{name}": ("<required_base_flag>",),')
    print("    2. Или добавить CRITICAL-пару в _FEATURE_FLAG_DEPENDENCIES_CRITICAL:")
    print(f'       "{name}": ("<required_base_flag>",),  # CRITICAL')
    print("    3. Или добавить комментарий # no dependency required в features.py")
    print()

    # --strict: blocking gate (exit 1 на нарушения)
    # без --strict: informational (exit 0, чтобы CI не падал на предупреждениях)
    return 1 if strict_mode else 0


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Check feature flag dependencies")
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Blocking gate (exit 1 на нарушения)",
    )
    args = parser.parse_args()

    sys.exit(run_check(strict_mode=args.strict))
