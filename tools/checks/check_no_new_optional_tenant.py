"""AST gate: запрет новых optional tenant_id параметров (audit W0).

Per audit W0: «Запретить новые optional tenant parameters AST-gate'ом».

Проблема: ADR-0345 Option A требует обязательный TenantId на границах
user-data repository/service. Optional ``tenant_id: str | None = None``
в public API позволяет caller'у случайно или намеренно пропустить
tenant filter → cross-tenant data leak.

Gate scans AST для всех ``tenant_id: str | None = None`` или
``tenant_id: Optional[str] = None`` параметров в public functions
(methods не начинающиеся с ``_``).

Gate strategy:
- baseline_count = количество существующих optional tenant_id параметров;
- new_count = текущее количество;
- если new_count > baseline_count → FAIL (new addition);
- если new_count == baseline_count → PASS (no new additions);
- если new_count < baseline_count → PASS (someone refactored away).

Baseline фиксируется в ``.baselines/optional_tenant_baseline.json``.
При первом запуске (baseline file отсутствует) → write baseline и PASS.
При последующих запусках → compare с baseline.
"""

from __future__ import annotations

import argparse
import ast
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
SRC_ROOT = PROJECT_ROOT / "src" / "backend"
BASELINE_PATH = PROJECT_ROOT / ".baselines" / "optional_tenant_baseline.json"


def _is_public(node: ast.FunctionDef | ast.AsyncFunctionDef | ast.ClassDef) -> bool:
    """True если node — public API (не начинается с ``_``)."""
    if isinstance(node, ast.ClassDef):
        return not node.name.startswith("_")
    return not node.name.startswith("_")


def _is_optional_tenant_param(arg: ast.arg) -> str | None:
    """Вернуть source аннотации если arg — optional ``tenant_id: ... = None``.

    Detection:
    - arg.arg == "tenant_id"
    - annotation содержит "None" (str | None, Optional[str], Union[str, None])

    Args:
        arg: AST-аргумент функции.

    Returns:
        Source аннотации (например ``"str | None"``) либо ``None``, если это
        не optional ``tenant_id``.

    """
    if arg.arg != "tenant_id":
        return None
    # Annotation check.
    if arg.annotation is None:
        return None
    ann_src = ast.unparse(arg.annotation)
    if "None" not in ann_src:
        return None
    return ann_src


def _scan_optional_tenant(file: Path) -> list[dict]:
    """Scan ``file`` for optional ``tenant_id`` parameters в public API.

    Returns:
        List of dicts ``{file, qualified_name, arg, annotation, line}``.

        Note:
            ``line`` присутствует ТОЛЬКО для отчёта о перемещении. Идентичность
            контракта его не включает (см. :func:`_identity`) — иначе любое
            перемещение функции внутри файла выглядит как NEW + REMOVED.
    """
    findings: list[dict] = []
    try:
        content = file.read_text(encoding="utf-8", errors="ignore")
        tree = ast.parse(content)
    except SyntaxError:
        return findings

    rel = str(file.resolve().relative_to(PROJECT_ROOT.resolve()))

    def _record(
        func: ast.FunctionDef | ast.AsyncFunctionDef, qualified: str, ann: str
    ) -> None:
        """Добавить finding; line — только для отчёта о перемещении."""
        findings.append(
            {
                "file": rel,
                "qualified_name": qualified,
                "arg": "tenant_id",
                "annotation": ann,
                "line": func.lineno,
            }
        )

    def _scan_function(
        func: ast.FunctionDef | ast.AsyncFunctionDef, class_name: str = ""
    ) -> None:
        """Recursively scan function + nested classes."""
        if not _is_public(func):
            return
        qualified = f"{class_name}.{func.name}" if class_name else func.name
        # Positional args: trailing args have defaults.
        pos_args = func.args.args
        n_pos = len(pos_args)
        n_pos_defaults = len(func.args.defaults)
        # Map positional defaults к trailing positional args.
        for i, default in enumerate(func.args.defaults):
            arg = pos_args[n_pos - n_pos_defaults + i]
            if isinstance(default, ast.Constant) and default.value is None:
                ann = _is_optional_tenant_param(arg)
                if ann is not None:
                    _record(func, qualified, ann)
        # Keyword-only args: каждый имеет свой default (kw_defaults).
        for arg, default in zip(func.args.kwonlyargs, func.args.kw_defaults):
            if default is None:
                continue
            if isinstance(default, ast.Constant) and default.value is None:
                ann = _is_optional_tenant_param(arg)
                if ann is not None:
                    _record(func, qualified, ann)

    def _scan_class(cls: ast.ClassDef) -> None:
        """Scan class body для public methods + nested classes."""
        if not _is_public(cls):
            return
        for stmt in cls.body:
            if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef)):
                _scan_function(stmt, cls.name)
            elif isinstance(stmt, ast.ClassDef):
                _scan_class(stmt)  # nested class

    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) or isinstance(node, ast.AsyncFunctionDef):
            # Top-level function (skip class methods, обработаны через ClassDef).
            # ast.walk даёт все nodes, но _scan_function вызывается
            # только для top-level (не вложенные в ClassDef). Для
            # вложенных мы scan внутри _scan_class.
            pass
        elif isinstance(node, ast.ClassDef):
            _scan_class(node)

    # Top-level functions.
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            _scan_function(node)

    return findings


def _collect_all_findings() -> list[dict]:
    """Collect all optional tenant_id findings across src/."""
    findings: list[dict] = []
    for py in SRC_ROOT.rglob("*.py"):
        if "__pycache__" in py.parts:
            continue
        if "/tests/" in str(py) or "/examples/" in str(py):
            continue
        findings.extend(_scan_optional_tenant(py.resolve()))
    return findings


def _identity(finding: dict) -> tuple[str, str, str]:
    """Идентичность optional-tenant контракта: module + qualified name + argument.

    Номер строки намеренно ИСКЛЮЧЁН. Раньше ключ был
    ``(file, line, qualified_name)``, из-за чего перемещение функции внутри
    файла давало ложные NEW + REMOVED: контракт не менялся, менялась только
    позиция. Практическое следствие было обратным требуемому — «починить»
    гейт можно было только перезаписью baseline, то есть замаскировать его.

    Args:
        finding: Элемент findings/baseline (dict).

    Returns:
        Кортеж ``(file, qualified_name, arg)`` — стабильный при перемещении.

    """
    return (
        str(finding.get("file", "")),
        str(finding.get("qualified_name", "")),
        str(finding.get("arg", "tenant_id")),
    )


def _read_baseline() -> list[dict] | None:
    """Read baseline findings (или None если файл отсутствует)."""
    if not BASELINE_PATH.is_file():
        return None
    try:
        return json.loads(BASELINE_PATH.read_text(encoding="utf-8"))
    except OSError, json.JSONDecodeError:
        return None


def _write_baseline(findings: list[dict]) -> None:
    """Write baseline findings в JSON."""
    BASELINE_PATH.parent.mkdir(parents=True, exist_ok=True)
    BASELINE_PATH.write_text(
        json.dumps(findings, indent=2, ensure_ascii=False, sort_keys=True),
        encoding="utf-8",
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "AST gate: запрет новых optional tenant_id параметров. "
            "Per audit W0: «Запретить новые optional tenant parameters AST-gate'ом»."
        )
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Exit 1 если найдены NEW optional tenant_id параметры.",
    )
    parser.add_argument("--json", action="store_true", help="JSON output.")
    parser.add_argument(
        "--update-baseline",
        action="store_true",
        help="Обновить baseline (для intentional refactors).",
    )
    args = parser.parse_args(argv)

    current = _collect_all_findings()
    baseline = _read_baseline()

    if args.update_baseline:
        _write_baseline(current)
        sys.stdout.write(
            f"✅ Baseline обновлён: {len(current)} optional tenant_id параметров.\n"
            f"  Файл: {BASELINE_PATH.relative_to(PROJECT_ROOT)}\n"
        )
        return 0

    if baseline is None:
        # First run — establish baseline.
        _write_baseline(current)
        sys.stdout.write(
            f"⚠️  Baseline создан ({len(current)} optional tenant_id параметров). "
            f"Subsequent runs будут FAIL на NEW additions.\n"
        )
        if args.json:
            sys.stdout.write(
                json.dumps(
                    {
                        "baseline_established": True,
                        "count": len(current),
                        "findings": current,
                    },
                    indent=2,
                    ensure_ascii=False,
                )
                + "\n"
            )
        return 0

    # Compare current vs baseline по identity БЕЗ номера строки.
    baseline_by_id = {_identity(f): f for f in baseline}
    current_by_id = {_identity(f): f for f in current}
    new_findings = [
        current_by_id[k] for k in current_by_id.keys() - baseline_by_id.keys()
    ]
    removed_findings = [
        baseline_by_id[k] for k in baseline_by_id.keys() - current_by_id.keys()
    ]

    # moved/changed — один и тот же контракт, изменилось только положение
    # или форма аннотации. НЕ являются нарушением (и не должны его давать).
    moved_findings: list[dict] = []
    changed_findings: list[dict] = []
    for key in current_by_id.keys() & baseline_by_id.keys():
        cur = current_by_id[key]
        base = baseline_by_id[key]
        base_line = base.get("line")
        if base_line is not None and base_line != cur.get("line"):
            moved_findings.append(
                {
                    "file": cur["file"],
                    "qualified_name": cur["qualified_name"],
                    "from_line": base_line,
                    "to_line": cur.get("line"),
                }
            )
        base_ann = base.get("annotation")
        # None = baseline старого формата (аннотация не записана) — не шумим.
        if base_ann is not None and base_ann != cur.get("annotation"):
            changed_findings.append(
                {
                    "file": cur["file"],
                    "qualified_name": cur["qualified_name"],
                    "from_annotation": base_ann,
                    "to_annotation": cur.get("annotation"),
                }
            )

    new_findings.sort(key=_identity)
    removed_findings.sort(key=_identity)

    if args.json:
        sys.stdout.write(
            json.dumps(
                {
                    "baseline_count": len(baseline),
                    "current_count": len(current),
                    "new_findings": new_findings,
                    "removed_findings": removed_findings,
                    "moved_findings": moved_findings,
                    "changed_findings": changed_findings,
                    "status": "FAIL" if new_findings else "PASS",
                },
                indent=2,
                ensure_ascii=False,
            )
            + "\n"
        )
    else:
        sys.stdout.write(
            f"Optional tenant_id AST gate (audit W0)\n"
            f"  Baseline: {len(baseline)} параметров\n"
            f"  Current:  {len(current)} параметров\n"
        )
        if new_findings:
            sys.stdout.write(
                "  ❌ NEW optional tenant_id parameters (need fix или baseline update):\n"
            )
            for f in new_findings:
                sys.stdout.write(
                    f"    - {f['file']}:{f.get('line')} {f['qualified_name']}\n"
                )
        if changed_findings:
            sys.stdout.write(
                "  ⚠️  CHANGED optional tenant_id signature (проверь вручную):\n"
            )
            for f in changed_findings:
                sys.stdout.write(
                    f"    - {f['file']} {f['qualified_name']}: "
                    f"{f['from_annotation']} -> {f['to_annotation']}\n"
                )
        if moved_findings:
            sys.stdout.write(
                "  ℹ️  MOVED optional tenant_id parameters (не нарушение):\n"
            )
            for f in moved_findings:
                sys.stdout.write(
                    f"    - {f['file']} {f['qualified_name']}: "
                    f"line {f['from_line']} -> {f['to_line']}\n"
                )
        if removed_findings:
            sys.stdout.write(
                "  ℹ️  REMOVED optional tenant_id parameters (auto-cleanup baseline):\n"
            )
            for f in removed_findings:
                sys.stdout.write(
                    f"    - {f['file']}:{f.get('line')} {f['qualified_name']}\n"
                )
        if not (new_findings or removed_findings or moved_findings or changed_findings):
            sys.stdout.write("  ✅ No drift\n")

    if args.strict and new_findings:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
