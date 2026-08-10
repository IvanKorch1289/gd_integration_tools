"""Targeted regression: PROJECT_PLAN.md как canonical roadmap (Sprint 7 Docs).

Этот тест проверяет, что `docs/PROJECT_PLAN.md` существует и содержит
обязательные секции, на которые ссылаются AGENTS.md, CLAUDE.md,
docs/adr/WIKI.md и docs/adr/0249 как на replacement для отсутствующего
PLAN.md.

Не запускает sphinx-build / не открывает файлы вне `docs/`.
"""

from __future__ import annotations

import re
from pathlib import Path

# Корневой путь: tests/unit/docs/test_project_plan.py -> подъём на 3 уровня.
_PROJECT_ROOT = Path(__file__).parents[3]
_DOCS_DIR = _PROJECT_ROOT / "docs"
_PROJECT_PLAN = _DOCS_DIR / "PROJECT_PLAN.md"


def test_project_plan_md_exists() -> None:
    """docs/PROJECT_PLAN.md существует как replacement для PLAN.md."""
    assert _PROJECT_PLAN.exists(), (
        f"Canonical roadmap отсутствует: {_PROJECT_PLAN}. "
        "PROJECT_PLAN.md должен заменить отсутствующий PLAN.md, "
        "на который ссылаются AGENTS.md, CLAUDE.md, docs/adr/WIKI.md, "
        "docs/adr/0249-dsl-upper-layer-imports-debt.md."
    )
    assert _PROJECT_PLAN.is_file()


def test_project_plan_md_non_empty() -> None:
    """PROJECT_PLAN.md — не пустой и не stub."""
    content = _PROJECT_PLAN.read_text(encoding="utf-8")
    assert len(content) > 2000, (
        f"PROJECT_PLAN.md слишком короткий ({len(content)} chars); "
        "минимальный canonical roadmap должен содержать V22 status, "
        "Sprint 1-8 status, target 9/10 на доменах."
    )


def test_project_plan_declares_v22_frozen() -> None:
    """Декларация V22 как зафиксированный baseline."""
    content = _PROJECT_PLAN.read_text(encoding="utf-8")
    assert "V22 зафиксирован" in content or "V22 фиксирован" in content, (
        "PROJECT_PLAN.md должен явно зафиксировать V22 как baseline."
    )
    # Архитектурные инварианты V22 (subset обязательных маркеров).
    required_invariants = (
        "4-layer",
        "Capability-checked facades",
        "Multi-protocol",
    )
    missing = [inv for inv in required_invariants if inv not in content]
    assert not missing, (
        f"V22 invariants отсутствуют в PROJECT_PLAN.md: {missing}"
    )


def test_project_plan_sprint_1_to_8_status() -> None:
    """Sprint 1-8 status matrix присутствует."""
    content = _PROJECT_PLAN.read_text(encoding="utf-8")
    # Все 8 спринтов должны быть упомянуты.
    required_sprints = [f"**Sprint {i}**" for i in range(1, 9)]
    missing = [s for s in required_sprints if s not in content]
    assert not missing, f"Отсутствуют записи Sprint 1-8: {missing}"

    # Колонка статуса: ловит canonical маркеры + расширения (partial→S8A и т.п.).
    # Sprint статусы — closed/partial/closure/blocked; обозначаются ✅/🟡/⚠️/🔴.
    sprint_rows = re.findall(
        r"\*\*Sprint \d+\*\* \| .+? \| (\S+).*?",
        content,
    )
    valid_status_prefixes = ("✅", "🟡", "⚠️", "🔴")
    assert len(sprint_rows) == 8, (
        f"Sprint status rows должно быть ровно 8 (найдено {len(sprint_rows)})."
    )
    bad = [s for s in sprint_rows if not s.startswith(valid_status_prefixes)]
    assert not bad, (
        f"Sprint статус без canonical emoji-маркера: {bad}. "
        "Допустимы: ✅ closed, 🟡 partial, ⚠️ closure, 🔴 blocked."
    )


def test_project_plan_target_9_per_10_per_domain() -> None:
    """Target 9/10 на каждом из доменов зафиксирован."""
    content = _PROJECT_PLAN.read_text(encoding="utf-8")
    assert "Target 9/10" in content or "9/10" in content, (
        "PROJECT_PLAN.md должен содержать target 9/10 maturity score по доменам."
    )

    # Домены (минимальный набор).
    required_domains = (
        "DSL builders",
        "AI Gateway",
        "Workflows",
        "Auth facade",
        "Storage facade",
        "Cache facade",
        "External HTTP",
        "CDC",
        "Agent isolation",
        "Notifications",
    )
    missing = [d for d in required_domains if d not in content]
    assert not missing, (
        f"Домены отсутствуют в PROJECT_PLAN.md target matrix: {missing}"
    )


def test_project_plan_references_canonical_sources() -> None:
    """Cross-references на canonical sources присутствуют (ARCHITECTURE, AGENTS, CLAUDE, ADR WIKI, ADR 0249)."""
    content = _PROJECT_PLAN.read_text(encoding="utf-8")
    expected_refs = [
        "ARCHITECTURE.md",
        "AGENTS.md",
        "CLAUDE.md",
        "docs/adr/WIKI.md",
        "0249",
    ]
    missing = [r for r in expected_refs if r not in content]
    assert not missing, (
        f"PROJECT_PLAN.md cross-references отсутствуют: {missing}. "
        "Должен явно ссылаться на canonical sources, которые ссылались "
        "на отсутствующий PLAN.md."
    )


def test_project_plan_replaces_plan_md_notion() -> None:
    """PROJECT_PLAN.md декларирует замещение отсутствующего PLAN.md."""
    content = _PROJECT_PLAN.read_text(encoding="utf-8")
    assert "PLAN.md" in content, (
        "PROJECT_PLAN.md должен явно упоминать PLAN.md как заменяемый документ."
    )
    # Должна присутствовать явная нота о replacement.
    replacement_phrases = (
        "replacement for",
        "replaces",
        "замен",
        "replacement",
    )
    has_replacement_note = any(p.lower() in content.lower() for p in replacement_phrases)
    assert has_replacement_note, (
        "PROJECT_PLAN.md должен содержать explicit replacement note для PLAN.md."
    )


def test_project_plan_has_changelog_section() -> None:
    """PROJECT_PLAN.md имеет changelog-секцию (binding к V22 era)."""
    content = _PROJECT_PLAN.read_text(encoding="utf-8")
    assert "Changelog" in content or "changelog" in content, (
        "PROJECT_PLAN.md должен содержать секцию changelog для фиксации future правок V22-invariants."
    )


def test_project_plan_does_not_introduce_destructive_edits() -> None:
    """PROJECT_PLAN.md не вводит новых ссылок на lock/secrets paths.

    Документ ЛЕГИТИМНО может упоминать `.env`, `.pem`, `.key`, `secrets/`
    в контексте объявления архитектурных правил/запретов (как в D248:
    ".env STRICTLY forbidden"). Такие упоминания — допустимы, поскольку
    описывают правило, а не указывают на секрет-файл.
    """
    content = _PROJECT_PLAN.read_text(encoding="utf-8")

    # Rule-context markers: слова, после которых .env/.pem/.key/secrets —
    # это описание правила (forbidden, deprecated, denied, запрещ, и т.п.).
    rule_context_re = re.compile(
        r"(STRICTLY\s+forbidden|forbidden|denied|запрещ|deprecated|prohibit|not\s+allowed|deny-list)",
        re.IGNORECASE,
    )

    # Ищем «реальные» ссылки (вне rule-context).
    forbidden_patterns = (
        (r"\.env(?!\w)", ".env"),
        (r"\.pem\b", ".pem"),
        (r"\.key\b", ".key"),
        (r"secrets/\*\*", "secrets/**"),
    )
    bad: list[tuple[str, int]] = []
    for pat, label in forbidden_patterns:
        for m in re.finditer(pat, content):
            # Берём окно контекста ±80 символов вокруг совпадения.
            start = max(0, m.start() - 80)
            end = min(len(content), m.end() + 80)
            ctx = content[start:end]
            if not rule_context_re.search(ctx):
                line_no = content.count("\n", 0, m.start()) + 1
                bad.append((label, line_no))
    assert not bad, (
        f"PROJECT_PLAN.md содержит ссылки на forbidden paths вне rule-context: {bad}. "
        "Если описание правила (например, '.env STRICTLY forbidden') — "
        "это ОК; иначе — заменить на абстрактное описание."
    )


def test_project_plan_uses_russian_documentation_convention() -> None:
    """PROJECT_PLAN.md следует Russian-first convention (per AGENTS.md §Стиль ответов)."""
    content = _PROJECT_PLAN.read_text(encoding="utf-8")
    # Минимальный набор русскоязычных терминов должен присутствовать.
    ru_markers = ("V22 зафиксирован", "Статус", "Домен")
    found = [m for m in ru_markers if m in content]
    assert found, (
        "PROJECT_PLAN.md должен следовать Russian-first convention "
        f"(найдено маркеров: {len(found)}/{len(ru_markers)})."
    )
