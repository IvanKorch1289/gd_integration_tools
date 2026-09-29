#!/usr/bin/env .venv/bin/python
"""Audit callsite deprecation checker (S105 W2 — deprecate-only).

Soft-deprecation policy для legacy ``_emit_audit`` / ``_emit_audit_safe``
callsites. Согласно S105 consult (выбор path B), этот скрипт:

1. **НЕ МЕНЯЕТ** существующие callsites (zero risk).
2. **ВЫЯВЛЯЕТ** все legacy callsites + per-file breakdown.
3. **EXIT 0** в default mode (для локального использования / pre-commit).
4. **EXIT 1** в ``--strict`` mode (для CI gate, когда baseline зафиксирован).

Canonical path (S103 W3 facade):
    ``from src.backend.core.audit.facade import emit_audit``

Usage:
    .venv/bin/python tools/check_audit_deprecation.py           # default
    .venv/bin/python tools/check_audit_deprecation.py --strict  # CI gate
    .venv/bin/python tools/check_audit_deprecation.py --json    # JSON output

Per subagent-2 finding (2026-06-13):
    * 69 matches ``_emit_audit`` + 8 matches ``_emit_audit_safe`` = 77 total.
    * 23 файлов в src/. 0 в extensions/ / routes/ / plugins/.
    * Две несовместимые архитектуры (DI callback vs service-locator) — full
      migration = multi-sprint. Этот скрипт = soft gate, не migration.
"""
from __future__ import annotations

import argparse
import ast
import json
import re
import sys
from collections import defaultdict
from pathlib import Path

__all__ = ("AuditDeprecationChecker", "main")


# Patterns для поиска legacy callsites.
# \b — word boundary, чтобы не ловить подстроки (например, ``my_emit_audit_helper``).
LEGACY_PATTERNS = (
    re.compile(r"\b_emit_audit_safe\b"),
    re.compile(r"\b_emit_audit\b"),
)

# Пути, которые исключаем из проверки:
# 1. Сам facade (canonical location, не legacy).
# 2. Test-файлы (там могут быть mock'и, это не production code).
# 3. testkit — служебные утилиты, не domain code.
EXCLUDE_PATH_SUBSTRINGS = (
    "/core/audit/facade.py",
    "/tests/",
    "/testkit/",
    "/__pycache__/",
    ".venv/",
    "/.cache/",  # S121 W1: build cache snapshots from parallel workers
    # Сам скрипт — содержит ``_emit_audit`` в docstring, не production code.
    "/tools/check_audit_deprecation.py",
)

# S111 W3: allowlist для mixin-internal callsites (TD-004 closure).
# Эти 8 файлов содержат ``self._emit_audit(...)`` / ``_emit_audit_safe(...)``
# вызовы, которые ЯВЛЯЮТСЯ частью dual-emit pattern (S106 W5): миксины
# дополнительно пишут через canonical facade (``emit_audit``), но ВНУТРИ
# себя всё ещё дёргают legacy ``_emit_audit`` для backward compat с
# pre-S103 call-sites (до того, как facade был введён).
#
# Эти callsites — НЕ техдолг, а часть стабильного API миксинов. Полная
# миграция на facade-only требует multi-sprint (TD-004 в TECH_DEBT).
# Allowlist формализует "expected residual" → 0 NEW violations в ratchet.
LEGITIMATE_MIXIN_FILES = (
    # Net layer: outbound HTTP middleware dual-emit (S109 W1).
    "src/backend/core/net/outbound_http.py",
    # Capability / authorization mixins (S103 W3 dual-emit bridge).
    "src/backend/core/security/activity_capability_guard.py",
    "src/backend/core/security/authorization_gateway/__init__.py",
    "src/backend/core/security/authorization_gateway/audit_mixin.py",
    "src/backend/core/security/capabilities/gate/__init__.py",
    "src/backend/core/security/capabilities/gate/_protocol.py",
    "src/backend/core/security/capabilities/gate/audit_mixin.py",
    "src/backend/core/security/capabilities/gate/check_mixin.py",
    "src/backend/core/security/capabilities/gate/declaration_mixin.py",
    # S121 W1: class-internal dual-emit pattern (self._emit_audit внутри
    # собственного class — class определяет _emit_audit helper и зовёт
    # его из своих методов; НЕ legacy callsite, а standard pattern).
    "src/backend/entrypoints/middlewares/observability.py",
    "src/backend/dsl/engine/processors/security/card_tokenize.py",
    "src/backend/dsl/engine/processors/security/pii_erase.py",
    "src/backend/services/pii/facade.py",
    # Тот же class-internal pattern: класс определяет `_emit_audit`
    # (hitl_service.py:240) и вызывает `self._emit_audit(...)` из своего
    # же метода (строка 180). Добавлен 2026-09-29 — файл отсутствовал в
    # списке, хотя структурно идентичен четырём записям выше.
    "src/backend/services/workflows/hitl_service.py",
)


def _file_class_index(content: str) -> dict[str, dict[str, object]]:
    """Собрать по исходнику карту ``class -> {bases, defines_emit_audit, строки}``.

    Args:
        content: исходный код файла.

    Returns:
        dict: имя класса → параметры. При нечитаемом исходнике — пустой dict.

    """
    try:
        tree = ast.parse(content)
    except SyntaxError:
        return {}
    index: dict[str, dict[str, object]] = {}
    for node in ast.walk(tree):
        if not isinstance(node, ast.ClassDef):
            continue
        defines = any(
            isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef))
            and item.name == "_emit_audit"
            for item in node.body
        )
        index[node.name] = {
            "bases": [b.id for b in node.bases if isinstance(b, ast.Name)],
            "defines": defines,
            "start_lineno": node.lineno,
            "end_lineno": node.end_lineno or node.lineno,
        }
    return index


def _enclosing_class(index: dict[str, dict[str, object]], lineno: int) -> str | None:
    """Найти самый вложенный класс, содержащий строку.

    Args:
        index: карта классов файла (см. :func:`_file_class_index`).
        lineno: номер строки, 1-based.

    Returns:
        Имя класса либо None, если строка вне тел классов (module-level вызов).

    """
    best: str | None = None
    best_span: int | None = None
    for name, meta in index.items():
        start, end = meta.get("start_lineno"), meta.get("end_lineno")
        if not isinstance(start, int) or not isinstance(end, int):
            continue
        if start <= lineno <= end:
            span = end - start
            if best_span is None or span < best_span:
                best, best_span = name, span
    return best


def _base_defines_emit_audit(
    base_names: list[str],
    global_index: dict[str, dict[str, dict[str, object]]],
    seen: set[str] | None = None,
) -> bool:
    """Определяет ли кто-то из базовых классов ``_emit_audit``.

    Обход ограничен по числу посещённых имён — защита от циклических иерархий.

    Args:
        base_names: имена прямых базовых классов.
        global_index: ``file -> {class -> meta}`` по production-файлам.
        seen: уже посещённые имена классов.

    Returns:
        True если в цепочке базовых классов есть определение ``_emit_audit``.

    """
    seen = set() if seen is None else seen
    if len(seen) > 64:
        return False
    for classes in global_index.values():
        for name in base_names:
            if name in seen or name not in classes:
                continue
            seen.add(name)
            meta = classes[name]
            if meta["defines"]:
                return True
            bases = meta["bases"]
            if isinstance(bases, list) and _base_defines_emit_audit(
                [b for b in bases if isinstance(b, str)], global_index, seen
            ):
                return True
    return False


class AuditDeprecationChecker:
    """Поиск legacy ``_emit_audit*`` callsites в production code.

    Args:
        root: корень репозитория (default ``.``).
    """

    def __init__(self, root: Path = Path(".")) -> None:
        self._root = root
        # results: {filename: [(line_no, line, pattern_name), ...]}
        self._results: dict[str, list[tuple[int, str, str]]] = defaultdict(list)
        self._scanned_files = 0

    def scan(self) -> dict[str, list[tuple[int, str, str]]]:
        """Сканировать ``.py`` файлы под ``root``.

        Returns:
            dict: filename → list of (line_no, line, pattern_name).
        """
        candidates: dict[str, list[tuple[int, str, str]]] = defaultdict(list)
        class_index: dict[str, dict[str, dict[str, object]]] = {}
        for py_file in self._root.rglob("*.py"):
            if self._hard_excluded(py_file):
                continue
            try:
                content = py_file.read_text(encoding="utf-8")
            except (UnicodeDecodeError, OSError):
                continue
            rel_path = str(py_file.relative_to(self._root))
            # Индекс строится и по allowlisted-файлам: базовые классы живут
            # именно там (например gate/_protocol.py).
            class_index[rel_path] = _file_class_index(content)
            if self._is_allowlisted(py_file):
                continue
            self._scanned_files += 1
            for line_no, line in enumerate(content.splitlines(), start=1):
                for pattern in LEGACY_PATTERNS:
                    if pattern.search(line):
                        # Получаем имя паттерна (для reporting).
                        # re.Pattern.search match object → взять из самого pattern.
                        pattern_name = (
                            "_emit_audit_safe"
                            if "safe" in pattern.pattern
                            else "_emit_audit"
                        )
                        candidates[rel_path].append(
                            (line_no, line.strip(), pattern_name)
                        )

        # S106 W5: вызов ``self._emit_audit(...)``, резолвящийся в УНАСЛЕДОВАННЫЙ
        # dual-emit миксин, не является legacy-callsite — regex сработал только на
        # имени. Вызовы вне классов и определения методов остаются legacy.
        for rel_path, items in candidates.items():
            classes = class_index.get(rel_path, {})
            for line_no, line, pattern_name in items:
                owner = _enclosing_class(classes, line_no)
                if owner is not None:
                    # Только S106 W5 (унаследованный dual-emit миксин).
                    # S121 W1 (class-internal helper) НЕ резолвится здесь
                    # намеренно: определение ``def _emit_audit`` в классе само
                    # по себе остаётся legacy-поверхностью, и проект закрывает
                    # такой случай allowlist'ом (см. LEGITIMATE_MIXIN_FILES),
                    # а не правилом детектора.
                    bases = classes[owner]["bases"]
                    if isinstance(bases, list) and _base_defines_emit_audit(
                        [b for b in bases if isinstance(b, str)], class_index
                    ):
                        continue  # S106 W5: унаследованный dual-emit миксин
                self._results[rel_path].append((line_no, line, pattern_name))
        return dict(self._results)

    def _hard_excluded(self, path: Path) -> bool:
        """Файл лежит в служебном пути (tests/.venv/__pycache__/сам скрипт).

        Args:
            path: путь к файлу.

        Returns:
            True если файл не является production-кодом.

        """
        path_str = path.as_posix()
        path_str_with_slash = path_str if path_str.startswith("/") else "/" + path_str
        return any(
            excl in path_str or excl in path_str_with_slash
            for excl in EXCLUDE_PATH_SUBSTRINGS
        )

    def _is_allowlisted(self, path: Path) -> bool:
        """Входит ли файл в ``LEGITIMATE_MIXIN_FILES`` (S111 W3).

        Args:
            path: путь к файлу.

        Returns:
            True если файл в allowlist.

        """
        path_str = path.as_posix()
        try:
            rel = path.relative_to(self._root).as_posix()
        except ValueError:
            rel = path_str
        return any(
            rel == allowlisted or rel.endswith(allowlisted)
            for allowlisted in LEGITIMATE_MIXIN_FILES
        )

    def _should_exclude(self, path: Path) -> bool:
        """Исключать ли файл из ПОИСКА callsites.

        Отдельно от :meth:`_hard_excluded`, потому что индекс классов строится
        по всем production-файлам, включая allowlisted: иначе базовый класс не
        резолвится и его наследники ошибочно считаются legacy. Например
        ``gate/_protocol.py`` в allowlist, но именно он определяет
        ``_CapabilityGateProtocol._emit_audit``, на который опирается
        ``check_tenant_mixin.py``.

        Args:
            path: путь к файлу.

        Returns:
            True если файл не участвует в поиске callsites.

        """
        return self._hard_excluded(path) or self._is_allowlisted(path)

    @property
    def total_callsites(self) -> int:
        """Общее число callsites (по всем файлам)."""
        return sum(len(matches) for matches in self._results.values())

    @property
    def total_files(self) -> int:
        """Число файлов с хотя бы одним callsite."""
        return len(self._results)

    def report_human(self) -> str:
        """Human-readable отчёт (default mode)."""
        lines: list[str] = []
        lines.append("=" * 70)
        lines.append("Audit Deprecation Check (S105 W2 soft-deprecation)")
        lines.append("=" * 70)
        lines.append(f"Files scanned: {self._scanned_files}")
        lines.append(f"Files with legacy callsites: {self.total_files}")
        lines.append(f"Total legacy callsites: {self.total_callsites}")
        lines.append(f"Allowlisted (mixin-internal, S111 W3): {len(LEGITIMATE_MIXIN_FILES)} files")
        lines.append("")

        if not self._results:
            lines.append("[OK] No legacy _emit_ callsites found.")
            return "\n".join(lines)

        lines.append("[INFO] Legacy callsites by file:")
        for filename in sorted(self._results.keys()):
            count = len(self._results[filename])
            lines.append(f"  {filename}: {count}")
        lines.append("")
        lines.append(
            "[HINT] Per-file locations: re-run with --json for full details, "
            "or migrate to canonical facade:"
        )
        lines.append(
            "       from src.backend.core.audit.facade import emit_audit"
        )
        lines.append("=" * 70)
        return "\n".join(lines)

    def report_json(self) -> str:
        """JSON отчёт (для CI / автоматизации)."""
        data = {
            "scanned_files": self._scanned_files,
            "files_with_legacy": self.total_files,
            "total_callsites": self.total_callsites,
            "allowlisted_files": len(LEGITIMATE_MIXIN_FILES),
            "files": {
                filename: [
                    {
                        "line": line_no,
                        "pattern": pattern_name,
                        "context": line_text[:200],  # truncate
                    }
                    for line_no, line_text, pattern_name in matches
                ]
                for filename, matches in self._results.items()
            },
        }
        return json.dumps(data, ensure_ascii=False, indent=2)


def main() -> int:
    """CLI entry point.

    Returns:
        0 — default mode (always).
        1 — ``--strict`` mode и есть callsites (CI gate).
        2 — error.
    """
    parser = argparse.ArgumentParser(
        description="Audit callsite deprecation checker (S105 W2)."
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Exit 1 if any legacy callsite found (для CI gate).",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="JSON output вместо human-readable.",
    )
    parser.add_argument(
        "--root",
        default=".",
        type=Path,
        help="Корень для сканирования (default: .).",
    )
    parser.add_argument(
        "--show-allowlist",
        action="store_true",
        help="Показать LEGITIMATE_MIXIN_FILES (S111 W3) и выйти.",
    )
    args = parser.parse_args()

    if args.show_allowlist:
        print(f"LEGITIMATE_MIXIN_FILES ({len(LEGITIMATE_MIXIN_FILES)} files):")
        for f in LEGITIMATE_MIXIN_FILES:
            print(f"  {f}")
        return 0

    try:
        checker = AuditDeprecationChecker(root=args.root)
        checker.scan()
    except Exception as exc:
        print(f"[error] {type(exc).__name__}: {exc}", file=sys.stderr)
        return 2

    if args.json:
        print(checker.report_json())
    else:
        print(checker.report_human())

    if args.strict and checker.total_callsites > 0:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
