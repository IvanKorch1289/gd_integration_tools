"""Deadline propagation completeness checker (Sprint 12, ADR-0305).

Сканирует ``src/backend/dsl/engine/processors/`` для проверки полноты
интеграции с ``RequestContext.deadline_budget``.

Для каждого ``.py`` файла в DSL processors:
1. Находит все ``asyncio.wait_for(..., timeout=<expr>)`` вызовы.
2. Находит fan-out patterns (``asyncio.gather``, ``sub_executor``,
   ``_run_branch``, ``create_subprocess_*``) — для них тоже требуется
   admission control, даже если ``wait_for`` отсутствует.
3. Классифицирует файл:
   - **integrated**: timeout narrowed через ``min(..., deadline_budget.remaining())``
     или есть admission control через ``budget.is_expired()`` в начале ``process()``.
   - **partial**: есть deadline_budget reference, но не narrowing.
   - **legacy**: timeout/fanout используется как-есть, без deadline chain.
   - **no-pattern**: ни wait_for, ни fan-out (file не в scope проверки).

Использование::

    python tools/checks/check_deadline_propagation.py              # human-readable
    python tools/checks/check_deadline_propagation.py --strict    # exit 1 if issues
    python tools/checks/check_deadline_propagation.py --json      # machine output

Exit codes:
    0 — все DSL processors (wait_for + fanout) интегрированы
    1 — найдены legacy или partial processors (--strict)

Architectural reference:
    ADR-0305 (Deadline Propagation Chain).
    Каждый DSL processor, использующий ``asyncio.wait_for`` ИЛИ fan-out
    pattern (asyncio.gather, sub_executor, _run_branch, subprocess),
    должен либо:
    a) иметь admission control через ``RequestContext.deadline_budget.is_expired()``
       в начале ``process()``, либо
    b) narrow ``self._timeout`` через ``min(self._timeout, budget.remaining())``.

Это обеспечивает deadline propagation через всю маршрутную цепочку, включая
aggregator processors (MulticastProcessor, RecipientList, LoadBalancer,
DynamicRouter) которые делают fan-out без явного wait_for.
"""

from __future__ import annotations

import argparse
import ast
import json
import re
from dataclasses import dataclass
from pathlib import Path

# Корень репозитория (относительно tools/checks/).
REPO_ROOT = Path(__file__).resolve().parents[2]
DSL_PROCESSORS_DIR = REPO_ROOT / "src" / "backend" / "dsl" / "engine" / "processors"

# Pattern для поиска ``asyncio.wait_for(...timeout=X)``.
WAIT_FOR_RE = re.compile(
    r"asyncio\.wait_for\s*\(",
    re.MULTILINE,
)

# Fan-out patterns — code patterns that trigger parallel work or subprocess execution.
# Если файл содержит эти patterns, ему НУЖЕН admission control даже без wait_for.
FANOUT_PATTERNS = (
    "asyncio.gather",
    "asyncio.create_subprocess_exec",
    "asyncio.create_subprocess_shell",
    "SubPipelineExecutor.execute_route",
    "_run_branch",
    "registry.create_task",
)

# Признаки интеграции с deadline_budget.
DEADLINE_REFS = (
    "deadline_budget",
    "is_expired",
    "budget.remaining",
    "budget.share",
    "DeadlineBudget",
    "RequestContext.current",
)


@dataclass(frozen=True)
class WaitForCall:
    """Один вызов ``asyncio.wait_for`` в исходнике."""

    file: Path
    line: int
    snippet: str


@dataclass(frozen=True)
class ProcessorStatus:
    """Статус интеграции одного ``.py`` файла."""

    file: Path
    wait_for_calls: tuple[WaitForCall, ...]
    has_deadline_refs: bool
    has_admission_control: bool
    has_narrowing: bool
    has_fanout: bool
    fanout_patterns: tuple[str, ...]
    verdict: str  # "integrated" | "partial" | "legacy" | "no-pattern"


def _find_wait_for_calls(path: Path) -> list[WaitForCall]:
    """AST-поиск вызовов ``asyncio.wait_for`` в файле."""
    calls: list[WaitForCall] = []
    try:
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(path))
    except (SyntaxError, UnicodeDecodeError):
        return calls

    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        # ``asyncio.wait_for(...)`` — Attribute(value=Name(id="asyncio"), attr="wait_for")
        if (
            isinstance(func, ast.Attribute)
            and func.attr == "wait_for"
            and isinstance(func.value, ast.Name)
            and func.value.id == "asyncio"
        ):
            src_lines = source.splitlines()
            line_idx = min(node.lineno - 1, len(src_lines) - 1)
            # Возьмём саму строку + 1 после для контекста.
            snippet = src_lines[line_idx][:120].strip()
            calls.append(WaitForCall(file=path, line=node.lineno, snippet=snippet))
    return calls


def _file_has_text(path: Path, *needles: str) -> bool:
    """Возвращает True, если хотя бы одна из подстрок встречается в файле."""
    try:
        source = path.read_text(encoding="utf-8")
    except (SyntaxError, UnicodeDecodeError):
        return False
    return any(n in source for n in needles)


def _file_has_admission_control(path: Path) -> bool:
    """Проверяет наличие admission-control блока через ``is_expired()`` или ``remaining()``."""
    # Эвристика: файл содержит ``budget.is_expired()`` или ``budget.remaining() <= 0``
    # внутри try-блока, ссылающегося на RequestContext.
    if not _file_has_text(path, "RequestContext"):
        return False
    has_expired_check = _file_has_text(
        path,
        "is_expired",
        "remaining() <= 0",
        "remaining() <",
    )
    has_ctx_ref = _file_has_text(path, "RequestContext.current")
    return has_expired_check and has_ctx_ref


def _file_has_narrowing(path: Path) -> bool:
    """Проверяет наличие ``min(..., remaining())`` или ``min(self._timeout, ...)`` narrowing."""
    narrowing_patterns = (
        "min(self._timeout, remaining)",
        "min(remaining",
        "remaining() <= 0",
        "effective_timeout = min",
        "branch_budget = ctx.deadline_budget.share",
        "budget.share(",
        "budget.remaining()",
    )
    return _file_has_text(path, *narrowing_patterns)


def classify_processor(path: Path) -> ProcessorStatus:
    """Определяет статус интеграции deadline_budget в одном файле."""
    wait_for_calls = tuple(_find_wait_for_calls(path))

    # Detect fan-out patterns.
    try:
        source = path.read_text(encoding="utf-8")
    except (SyntaxError, UnicodeDecodeError):
        source = ""
    fanout_patterns_found = tuple(p for p in FANOUT_PATTERNS if p in source)
    has_fanout = bool(fanout_patterns_found)

    # Early exit: ни wait_for, ни fanout — файл не в scope проверки.
    if not wait_for_calls and not has_fanout:
        return ProcessorStatus(
            file=path,
            wait_for_calls=wait_for_calls,
            has_deadline_refs=False,
            has_admission_control=False,
            has_narrowing=False,
            has_fanout=False,
            fanout_patterns=(),
            verdict="no-pattern",
        )

    has_deadline_refs = _file_has_text(path, *DEADLINE_REFS)
    has_admission_control = _file_has_admission_control(path)
    has_narrowing = _file_has_narrowing(path)

    # Verdict:
    # - integrated: есть narrowing ИЛИ admission_control.
    # - partial: есть deadline_refs, но нет narrowing/admission_control.
    # - legacy: ни narrowing, ни admission_control.
    if has_admission_control or has_narrowing:
        verdict = "integrated"
    elif has_deadline_refs:
        verdict = "partial"
    else:
        verdict = "legacy"

    return ProcessorStatus(
        file=path,
        wait_for_calls=wait_for_calls,
        has_deadline_refs=has_deadline_refs,
        has_admission_control=has_admission_control,
        has_narrowing=has_narrowing,
        has_fanout=has_fanout,
        fanout_patterns=fanout_patterns_found,
        verdict=verdict,
    )


def _iter_dsl_processor_files() -> list[Path]:
    """Все ``.py`` файлы в ``src/backend/dsl/engine/processors/`` (включая подкаталоги).

    Исключения:
    - ``base.py``: utility module (BaseProcessor + SubPipelineExecutor),
      не самостоятельный processor — fanout pattern там определён для переиспользования.
    - ``__init__.py``: re-exports, не процессоры.
    - ``script_runner.py``: DISABLED (cycle-6/D-AUDIT-602 RCE fix) — fanout
      patterns в docstring описывают историческое поведение, но ``process()``
      всегда raise NotImplementedError.
    """
    if not DSL_PROCESSORS_DIR.exists():
        return []
    excluded = {"base.py", "__init__.py", "script_runner.py"}
    return sorted(
        p for p in DSL_PROCESSORS_DIR.rglob("*.py")
        if p.name not in excluded
    )


def scan() -> list[ProcessorStatus]:
    """Сканирует все DSL processors, возвращает статусы."""
    return [classify_processor(p) for p in _iter_dsl_processor_files()]


def render_human(results: list[ProcessorStatus]) -> str:
    """Human-readable отчёт."""
    lines: list[str] = []
    lines.append("=" * 78)
    lines.append("Deadline Propagation Completeness Check (ADR-0305)")
    lines.append("=" * 78)

    by_verdict: dict[str, list[ProcessorStatus]] = {}
    for r in results:
        by_verdict.setdefault(r.verdict, []).append(r)

    summary = {
        v: len(by_verdict.get(v, []))
        for v in ("integrated", "partial", "legacy", "no-pattern")
    }
    lines.append(
        f"Summary: integrated={summary['integrated']}, "
        f"partial={summary['partial']}, "
        f"legacy={summary['legacy']}, "
        f"no-pattern={summary['no-pattern']}"
    )
    lines.append("")

    # Legacy — критические.
    if by_verdict.get("legacy"):
        lines.append("--- LEGACY (wait_for/fanout без deadline_budget reference) ---")
        for r in by_verdict["legacy"]:
            rel = r.file.relative_to(REPO_ROOT)
            reasons: list[str] = []
            if r.wait_for_calls:
                reasons.append(f"{len(r.wait_for_calls)} asyncio.wait_for")
            if r.has_fanout:
                reasons.append(f"fanout={','.join(r.fanout_patterns[:3])}")
            for call in r.wait_for_calls:
                lines.append(
                    f"  {rel}:{call.line}  asyncio.wait_for(...) — no deadline chain"
                )
            if r.has_fanout and not r.wait_for_calls:
                lines.append(
                    f"  {rel}  fanout-only ({','.join(r.fanout_patterns[:3])}) — no deadline chain"
                )
        lines.append("")

    if by_verdict.get("partial"):
        lines.append("--- PARTIAL (has deadline_refs, but no narrowing/admission_control) ---")
        for r in by_verdict["partial"]:
            rel = r.file.relative_to(REPO_ROOT)
            for call in r.wait_for_calls:
                lines.append(f"  {rel}:{call.line}  asyncio.wait_for(...)")
        lines.append("")

    if by_verdict.get("integrated"):
        lines.append("--- INTEGRATED ---")
        for r in by_verdict["integrated"]:
            rel = r.file.relative_to(REPO_ROOT)
            indicators = []
            if r.has_narrowing:
                indicators.append("narrowing")
            if r.has_admission_control:
                indicators.append("admission_control")
            patterns_str = ""
            if r.has_fanout:
                patterns_str = f" [fanout: {','.join(r.fanout_patterns[:3])}]"
            for call in r.wait_for_calls:
                lines.append(
                    f"  {rel}:{call.line}  ({', '.join(indicators)}){patterns_str}"
                )
            if r.has_fanout and not r.wait_for_calls:
                lines.append(
                    f"  {rel}  ({', '.join(indicators)}){patterns_str}"
                )
        lines.append("")

    return "\n".join(lines)


def render_json(results: list[ProcessorStatus]) -> str:
    """JSON-отчёт для CI/автоматизации."""
    payload = {
        "total_processors": len(results),
        "summary": {
            v: sum(1 for r in results if r.verdict == v)
            for v in ("integrated", "partial", "legacy", "no-pattern")
        },
        "processors": [
            {
                "file": str(r.file.relative_to(REPO_ROOT)),
                "verdict": r.verdict,
                "wait_for_calls": [
                    {"line": c.line, "snippet": c.snippet} for c in r.wait_for_calls
                ],
                "has_deadline_refs": r.has_deadline_refs,
                "has_admission_control": r.has_admission_control,
                "has_narrowing": r.has_narrowing,
                "has_fanout": r.has_fanout,
                "fanout_patterns": list(r.fanout_patterns),
            }
            for r in results
        ],
    }
    return json.dumps(payload, indent=2, ensure_ascii=False)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Deadline propagation completeness checker (ADR-0305)."
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Exit 1 if any DSL processor has legacy or partial verdict.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit JSON instead of human-readable output.",
    )
    args = parser.parse_args()

    results = scan()
    if args.json:
        print(render_json(results))
    else:
        print(render_human(results))

    if args.strict:
        has_issues = any(r.verdict in ("legacy", "partial") for r in results)
        return 1 if has_issues else 0
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
