"""Regression-блокировка: 17 мигрированных файлов НЕ должны импортировать
``src.backend.core.frontend_facade`` (после cycles 207-209).

Это enforcement-тест для FRONTEND_FACADE_MIGRATION_FINAL.md
(cycle 209/210): все 17 файлов мигрированы. Если кто-то случайно
re-импортирует facade (например, при слиянии веток), этот тест упадёт
с понятным message.

**Проверяемые файлы** (по группам):
- HTTP migration (10):
  - 19_Saga_Компенсации.py, 33_DSL_Шаблоны.py, 17_Replay_Воркфлоу.py,
    workflow_templates_tab.py, 23_AI_Учёт_затрат.py,
    18_Версионирование_Воркфлоу.py, 15_Оценка_стоимости_Workflow.py,
    workflow_diff.py, 34_DSL_Отладчик.py
- Inlined pure utility (3):
  - yaml_sync.py, properties.py, visual/tab_canvas.py
- Documented intentional (4):
  - 32_DSL_Конструктор.py, 63_Вики.py,
    96_Монитор_зависших_сообщений.py, schema/import_tab.py

**Допустимые исключения** (intentional facade — задокументированы в M7):
- 32_DSL_Конструктор.py (service object: DSLBuilderService)
- 63_Вики.py (DI factory: WhooshIndexFactory)
- 96_Монитор_зависших_сообщений.py (service: StuckMonitor)
- schema/import_tab.py (service: ImportService)

Эти 4 файла ДОПУСКАЮТ facade import (per DEEP_AUDIT_R3.10d:
frontend ≠ extension, тонкая обёртка через facade allowed).
Тест проверяет только 13 файлов, которые ДОЛЖНЫ быть без facade.
"""

from __future__ import annotations

import re
from pathlib import Path

# 10 файлов которые НЕ ДОЛЖНЫ импортировать frontend_facade
# (HTTP migration only — эти файлы мигрированы на HTTP clients в cycle 207-208).
#
# NOTE: 3 inlined pure utility файла (_editor/yaml_sync.py, properties.py,
# visual/tab_canvas.py) БЫЛИ инлайнены в cycle 209, НО commit 5df08e40
# ("migrate _editor/ direct dsl imports to facade") их re-вёртнул обратно
# к facade импортам (per layer-rule reapply). Поэтому они не в списке
# forbidden — это текущее state of the art, защищённое layer-checker'ом.
_FORBIDDEN_FACADE_FILES = (
    "src/frontend/streamlit_app/pages/19_Saga_Компенсации.py",
    "src/frontend/streamlit_app/pages/33_DSL_Шаблоны.py",
    "src/frontend/streamlit_app/pages/17_Replay_Воркфлоу.py",
    "src/frontend/streamlit_app/pages/_groups/dsl/dsl_templates/workflow_templates_tab.py",
    "src/frontend/streamlit_app/pages/23_AI_Учёт_затрат.py",
    "src/frontend/streamlit_app/pages/18_Версионирование_Воркфлоу.py",
    "src/frontend/streamlit_app/pages/15_Оценка_стоимости_Workflow.py",
    "src/frontend/streamlit_app/pages/_editor/workflow_diff.py",
    "src/frontend/streamlit_app/pages/34_DSL_Отладчик.py",
    # HTTP migration в admin.py (добавлен list_workflow_templates в cycle 208)
    "src/frontend/streamlit_app/api_clients/admin.py",
    # NS-3 (cycle 32, production-grade plan): core-only symbols migrated
    # to ``src.backend.core.api``. Remaining 17 dsl_portal-файлов stay on
    # facade (YAGNI/ponytail — layer boundary frontend → services).
    "src/frontend/streamlit_app/app.py",
    "src/frontend/streamlit_app/pages/00_Вход.py",
    "src/frontend/streamlit_app/pages/10_Заказы.py",
    "src/frontend/streamlit_app/pages/_groups/schema/registry_tab.py",
    "src/frontend/streamlit_app/pages/52_Устойчивость.py",
    "src/frontend/streamlit_app/pages/54_Replay_DLQ.py",
    "src/frontend/streamlit_app/pages/55_Монитор_пула.py",
    "src/frontend/streamlit_app/pages/58_Шина_действий.py",
    "src/frontend/streamlit_app/pages/66_Логи_Воркфлоу.py",
    "src/frontend/streamlit_app/api_clients/k4.py",
    "src/frontend/streamlit_app/pages/43_Логи_в_реальном_времени.py",
    "src/frontend/streamlit_app/pages/36_Экспресс_боты.py",
    "src/frontend/streamlit_app/pages/_groups/replay/helpers.py",
    # NOT included: ``_groups/schema/import_tab.py`` uses dsl_portal
    # ImportSource/ImportSourceKind/get_import_service — stays on facade.
)

# Pattern: ``from src.backend.core.frontend_facade import ...``
# Допустимы docstring-упоминания (начинаются с #)
_FACADE_IMPORT_RE = re.compile(
    r"^(\s*)from\s+src\.backend\.core\.frontend_facade\s+import\s+(\S.*?)$",
    re.MULTILINE,
)

# Symbols which have HTTP equivalents (cycle 207-208) — MUST NOT be imported via facade
_SYMBOLS_WITH_HTTP_EQUIVALENT = frozenset(
    {
        "get_saga_history",  # /admin/workflows/{id}/saga-history
        "list_workflow_templates",  # /admin/workflow-templates/
        "get_ai_cost_snapshot",  # /admin/ai-costs
        "get_global_registry",  # /admin/workflow-versioning/{id}/history
        "list_route_ids",  # /dsl-routes
        "list_audit_records",  # /audit/capability
        "list_recent_trace_events",  # /workflow-audit/events
    }
)


def _check_file_no_facade_import(rel_path: str) -> str | None:
    """Return violation if file imports facade symbols that have HTTP equivalents."""
    path = Path(rel_path)
    if not path.exists():
        return f"file not found: {rel_path}"

    content = path.read_text(encoding="utf-8")
    # Strip docstring lines (для consistency с миграцией)
    non_docstring_lines = []
    in_docstring = False
    for line in content.splitlines():
        stripped = line.strip()
        if in_docstring:
            if '"""' in stripped or "'''" in stripped:
                in_docstring = False
            continue
        if '"""' in stripped or "'''" in stripped:
            in_docstring = True
            continue
        if stripped.startswith("#"):
            continue
        non_docstring_lines.append(line)
    clean_content = "\n".join(non_docstring_lines)

    for match in _FACADE_IMPORT_RE.finditer(clean_content):
        imported_names_str = match.group(2)
        # Парсим импортируемые имена (comma-separated)
        imported_names = [n.strip() for n in imported_names_str.split(",") if n.strip()]
        # Проверяем только символы с HTTP equivalents
        forbidden_imports = [
            n for n in imported_names if n in _SYMBOLS_WITH_HTTP_EQUIVALENT
        ]
        if forbidden_imports:
            return (
                f"Frontend facade re-imports HTTP-equivalent symbols in {rel_path}!\n"
                f"  Line: {match.group(0).strip()}\n"
                f"  Forbidden symbols: {', '.join(forbidden_imports)}\n"
                f"  These have HTTP endpoints (cycle 207-208 migration).\n"
                f"  Use HTTP clients (src.frontend.streamlit_app.api_clients) instead.\n"
                f"  See FRONTEND_FACADE_MIGRATION_FINAL.md for the pattern."
            )
    return None


def test_no_frontend_facade_imports_in_migrated_files() -> None:
    """10 файлов мигрированы на HTTP clients.

    Если какой-то из них re-импортирует ``frontend_facade`` для
    HTTP-equivalent symbols — этот тест падает.

    Допустимы facade imports для символов БЕЗ HTTP equivalents (например,
    search_workflow_templates, WorkflowDeclaration, compute_step_diff) —
    они остаются facade (M7 backlog).
    """
    violations: list[str] = []
    for rel_path in _FORBIDDEN_FACADE_FILES:
        msg = _check_file_no_facade_import(rel_path)
        if msg:
            violations.append(msg)

    assert not violations, (
        "Frontend facade re-imports HTTP-equivalent symbols "
        "(regression of cycle 207-208 migration):\n\n" + "\n\n".join(violations)
    )


def test_total_migrated_files_count() -> None:
    """Sanity: forbidden list покрывает HTTP + core-only migrations.

    NS-3 (cycle 32): +13 core-only файлов мигрированы на ``core.api``
    (1 dsl_portal file — ``import_tab.py`` — excluded: stays on facade
    with documented-intentional comment).
    Итого: 10 HTTP (cycle 207-208) + 13 core-only (cycle 32) = 23 файла.
    """
    # 10 HTTP (cycle 207-208) + 13 core-only (cycle 32 NS-3) = 23
    assert len(_FORBIDDEN_FACADE_FILES) == 23, (
        f"Expected 23 forbidden files (10 HTTP + 13 core-only), "
        f"got {len(_FORBIDDEN_FACADE_FILES)}. "
        f"Update if migration count changed."
    )


def test_documented_intentional_files_have_facade_docstring() -> None:
    """4 documented-intentional файла имеют explicit docstring про facade.

    Защита от «добавили новый service-object import без docstring» —
    тест требует explicit comment с обоснованием.
    """
    # Эти 4 файла легитимно используют facade (M7 backlog).
    # Per DEEP_AUDIT_R3.10d — frontend ≠ extension, facade allowed.
    documented_files = (
        "src/frontend/streamlit_app/pages/32_DSL_Конструктор.py",
        "src/frontend/streamlit_app/pages/63_Вики.py",
        "src/frontend/streamlit_app/pages/96_Монитор_зависших_сообщений.py",
        "src/frontend/streamlit_app/pages/_groups/schema/import_tab.py",
    )

    for rel_path in documented_files:
        path = Path(rel_path)
        if not path.exists():
            continue
        content = path.read_text(encoding="utf-8")
        # Ищем комментарий-обоснование (intentional / DEEP_AUDIT / R3.10d / M7)
        if not re.search(r"(intentional|DEEP_AUDIT|R3\.10d|M7)", content):
            raise AssertionError(
                f"{rel_path} uses frontend_facade but lacks "
                f"documented-intentional comment. "
                f"Add 'intentional layer-acknowledged exemption' or "
                f"'DEEP_AUDIT_R3.10d' reference."
            )
