"""Гейт актуальности RPA-документации (ADR-0370, cycle 172).

До cycle 172 ``docs/rpa/RPA_GUIDE.md`` содержал выдуманную
capability-таблицу: 16 из 33 имён отсутствовали в vocabulary
(``rpa.file.archive``, ``rpa.doc.pdf.read``, ``rpa.banking.citrix`` …),
а ``ImageConvertProcessor`` не существует в коде. ``docs/rpa/DSL_AUDIT.md``
устарел: 4 из 5 «GAP»-процессоров давно реализованы, а taxonomy
перечисляла несуществующие capability.

Проверки:

1. capability-таблица RPA_GUIDE.md == множество ``rpa.*`` в vocabulary;
2. каждый упомянутый в RPA_GUIDE.md / DSL_AUDIT.md ``*Processor``
   реально существует в ``src/backend``;
3. taxonomy в DSL_AUDIT.md ссылается на существующие capability.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

from src.backend.core.security.capabilities import build_default_vocabulary

_ROOT = Path(__file__).resolve().parents[2]
_SRC = _ROOT / "src" / "backend"
_RPA_GUIDE = _ROOT / "docs" / "rpa" / "RPA_GUIDE.md"
_DSL_AUDIT = _ROOT / "docs" / "rpa" / "DSL_AUDIT.md"

#: Capability-имя в тексте (внутри backticks).
_CAPABILITY = re.compile(r"rpa\.[a-z0-9_]+(?:\.[a-z0-9_]+)*")

#: Имя процессора в тексте (внутри backticks).
_PROCESSOR = re.compile(r"\b([A-Z][A-Za-z0-9]*Processor)\b")


def _processor_names() -> set[str]:
    """Все классы ``*Processor`` в ``src/backend`` (AST)."""
    names: set[str] = set()
    for path in _SRC.rglob("*.py"):
        if "__pycache__" in path.parts:
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except (SyntaxError, UnicodeDecodeError):
            continue
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef) and node.name.endswith("Processor"):
                names.add(node.name)
    return names


def _table_capabilities(document: str) -> set[str]:
    """Capability-имена из markdown-таблиц (строки, начинающиеся с ``| ``)."""
    found: set[str] = set()
    for line in document.splitlines():
        if not line.startswith("| "):
            continue
        for cell in line.split("|"):
            cell = cell.strip()
            if cell.startswith("`") and cell.endswith("`"):
                found.update(_CAPABILITY.findall(cell))
    return found


def _backticked_processor_names(document: str) -> set[str]:
    """Имена процессоров, упомянутых в backticks."""
    found: set[str] = set()
    for line in document.splitlines():
        for cell in re.findall(r"`([^`]+)`", line):
            found.update(_PROCESSOR.findall(cell))
    return found


def test_rpa_guide_capability_table_matches_vocabulary() -> None:
    """Capability-таблица RPA_GUIDE.md == rpa.* capability из vocabulary."""
    vocabulary = {
        definition.name
        for definition in build_default_vocabulary().all()
        if definition.name.startswith("rpa.")
    }
    documented = _table_capabilities(_RPA_GUIDE.read_text(encoding="utf-8"))

    assert documented == vocabulary, (
        "capability-таблица RPA_GUIDE.md расходится с vocabulary: "
        f"нет в докe={sorted(vocabulary - documented)}, "
        f"лишние в доке={sorted(documented - vocabulary)}"
    )


def _section(document: str, heading: str) -> str:
    """Текст раздела markdown по заголовку (до следующего ``##``)."""
    parts = document.split(heading, 1)
    if len(parts) == 1:
        return ""
    return parts[1].split("\n## ", 1)[0]


def test_rpa_guide_mentions_only_existing_processors() -> None:
    """В RPA_GUIDE.md нет выдуманных процессоров (напр. ImageConvertProcessor)."""
    existing = _processor_names()
    mentioned = _backticked_processor_names(_RPA_GUIDE.read_text(encoding="utf-8"))
    unknown = sorted(mentioned - existing)
    assert not unknown, f"RPA_GUIDE.md упоминает несуществующие процессоры: {unknown}"


def test_dsl_audit_existing_section_lists_existing_processors() -> None:
    """Раздел «Существующие процессоры» содержит только реальные классы."""
    existing = _processor_names()
    section = _section(_DSL_AUDIT.read_text(encoding="utf-8"), "## Существующие процессоры")
    unknown = sorted(_backticked_processor_names(section) - existing)
    assert not unknown, f"DSL_AUDIT.md упоминает несуществующие процессоры: {unknown}"


def test_dsl_audit_open_gaps_are_really_missing() -> None:
    """Открытые gaps действительно не реализованы."""
    existing = _processor_names()
    section = _section(_DSL_AUDIT.read_text(encoding="utf-8"), "## GAPS")
    implemented = sorted(_backticked_processor_names(section) & existing)
    assert not implemented, (
        f"GAPS-таблица содержит уже реализованные процессоры: {implemented}"
    )


def test_dsl_audit_closed_gaps_are_implemented() -> None:
    """Закрытые gaps действительно реализованы."""
    existing = _processor_names()
    section = _section(
        _DSL_AUDIT.read_text(encoding="utf-8"), "## Закрытые ранее пункты"
    )
    missing = sorted(_backticked_processor_names(section) - existing)
    assert not missing, (
        f"раздел «Закрытые ранее пункты» содержит несуществующие процессоры: {missing}"
    )


def test_dsl_audit_taxonomy_capabilities_exist() -> None:
    """Taxonomy DSL_AUDIT.md ссылается на существующие capability."""
    vocabulary = {definition.name for definition in build_default_vocabulary().all()}
    document = _DSL_AUDIT.read_text(encoding="utf-8")
    referenced = {
        name
        for line in document.splitlines()
        if "required_capability" in line
        for name in re.findall(r'"([a-z][a-z0-9_]*(?:\.[a-z0-9_]+)+)"', line)
    }
    unknown = sorted(referenced - vocabulary)
    assert not unknown, f"taxonomy ссылается на неизвестные capability: {unknown}"


def test_dsl_audit_has_no_stale_gap_entries() -> None:
    """GAPS-таблица DSL_AUDIT.md не содержит уже реализованных процессоров."""
    existing = _processor_names()
    document = _DSL_AUDIT.read_text(encoding="utf-8")
    gap_section = _section(document, "## GAPS")
    stale = sorted(_backticked_processor_names(gap_section) & existing)
    assert not stale, f"GAPS-таблица содержит уже реализованные процессоры: {stale}"
