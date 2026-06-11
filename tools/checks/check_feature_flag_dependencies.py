"""Check feature flag dependencies — lint для *_strict flags без declared dependencies.

Назначение:
    Проверяет что все *_strict feature flags в features.py (или в
    features/ package) объявлены либо:
    - в ``_FEATURE_FLAG_DEPENDENCIES`` (WARNING-level);
    - в ``_FEATURE_FLAG_DEPENDENCIES_CRITICAL`` (CRITICAL-level);
    - с явным комментарием ``# no dependency required`` рядом с полем.

    Парсит features.py (или все .py в features/ package) через AST и
    сверяет с validator.py константами. Соответствует S31 w1 Фаза D.
    Package-aware с S38 T1.3.0 (Sprint 38 разделил monolithic features.py
    в features/ package с per-domain sub-modules).

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
_FEATURES_FILE = _ROOT / "src/backend/core/config/features.py"
_FEATURES_PKG = _ROOT / "src/backend/core/config/features"


def _find_features_source() -> tuple[dict[str, int], str] | None:
    """Найти source для feature flag definitions.

    Поддерживает два layout'а:
    - Legacy: src/backend/core/config/features.py (single file)
    - Modern (S38 T1.3.0+): src/backend/core/config/features/__init__.py + sub-modules

    Returns:
        (strict_flags_dict, concatenated_source) или None если ничего не найдено.
        strict_flags_dict: name → lineno (в source-файле где определён).
    """
    strict_flags: dict[str, int] = {}
    sources: list[str] = []

    if _FEATURES_FILE.exists():
        # Legacy single-file layout
        src = _FEATURES_FILE.read_text()
        sources.append(f"# === {_FEATURES_FILE.name} ===\n{src}")
        tree = ast.parse(src)
        for node in ast.walk(tree):
            if isinstance(node, ast.Name) and node.id.endswith("_strict"):
                strict_flags[node.id] = node.lineno
        return strict_flags, "\n".join(sources)

    if _FEATURES_PKG.is_dir():
        # Modern package layout (S38+)
        for py_file in sorted(_FEATURES_PKG.glob("*.py")):
            if py_file.name == "__init__.py" and not list(
                _FEATURES_PKG.glob("[a-z]*.py")
            ):
                # No sub-modules — only __init__.py
                pass
            src = py_file.read_text()
            sources.append(f"# === {py_file.relative_to(_ROOT)} ===\n{src}")
            tree = ast.parse(src)
            # ast.AnnAssign: target=Name, annotation, value (Field(...)).
            # Ищем `name_strict: Type = Field(...)` — реальное определение флага.
            for node in ast.walk(tree):
                if isinstance(node, ast.AnnAssign) and isinstance(
                    node.target, ast.Name
                ):
                    if node.target.id.endswith("_strict"):
                        strict_flags[node.target.id] = node.target.lineno + sum(
                            s.count("\n") for s in sources[:-1]
                        )
        return strict_flags, "\n".join(sources)

    return None


def _parse_declared_dependencies(validator_py: str) -> tuple[set[str], set[str]]:
    """Парсит validator.py и возвращает множества declared dependencies."""
    warning_deps = set()
    critical_deps = set()

    # WARNING dict keys
    warning_match = re.findall(
        r'_FEATURE_FLAG_DEPENDENCIES\s*=\s*\{[^}]*"([^"]+)":', validator_py, re.DOTALL
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

    # S45 W3 (TD-018): _FEATURE_FLAG_DEPENDENCIES_STRICT_AUTOMAP — bulk
    # mapping для *X_strict → X (naming convention). Каждый ключ в
    # automap уже considered WARNING-declared (X_strict requires X).
    # Ищем сначала type-annotated `Final[frozenset[str]] = frozenset(`,
    # затем plain `frozenset(` (для back-compat).
    automap_match = re.findall(r"frozenset\(\s*\{([^}]+)\}", validator_py)
    if automap_match:
        for entry in automap_match:
            for key_match in re.findall(r'"([^"]+)"', entry):
                warning_deps.add(key_match.strip())

    return warning_deps, critical_deps


def _check_no_dep_required_comments(features_src: str) -> set[str]:
    """Находит strict flags с комментарием # no dependency required."""
    pattern = re.compile(
        r"^\s*(\w*_strict\w*)\s*:\s*[^#]*#.*no dependency required", re.MULTILINE
    )
    return {m.group(1) for m in pattern.finditer(features_src)}


def run_check(strict_mode: bool = False) -> int:
    """Основная проверка. Возвращает 0 если всё покрыто, 1 если нарушения."""
    if not _VALIDATOR_PATH.exists():
        print(f"[ERROR] validator.py не найден: {_VALIDATOR_PATH}", file=sys.stderr)
        return 1

    features_result = _find_features_source()
    if features_result is None:
        print(
            f"[ERROR] features source не найден: ни {_FEATURES_FILE}, ни {_FEATURES_PKG}/",
            file=sys.stderr,
        )
        return 1

    strict_flags, features_src = features_result
    validator_src = _VALIDATOR_PATH.read_text()

    warning_deps, critical_deps = _parse_declared_dependencies(validator_src)
    no_dep_required = _check_no_dep_required_comments(features_src)

    all_declared = warning_deps | critical_deps | no_dep_required
    undeclared = [name for name in strict_flags if name not in all_declared]

    if not undeclared:
        print(
            f"[OK] Все {len(strict_flags)} *_strict flags объявлены в dependencies или have no-dep comment."
        )
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
        "--strict", action="store_true", help="Blocking gate (exit 1 на нарушения)"
    )
    args = parser.parse_args()

    sys.exit(run_check(strict_mode=args.strict))
