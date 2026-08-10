"""Regression-тесты: docs/adr/WIKI.md не должен содержать битую ссылку на PLAN.md.

Контекст (Sprint 7 / Docs 3):
* PLAN.md не существует в репозитории (проверено: `ls /home/user/dev/gd_integration_tools/PLAN.md` → ENOENT).
* WIKI.md генерируется из `tools/build_adr_wiki.py` (auto-generated footer).
* Без root-cause fix в build_adr_wiki.py следующий sync (adr-sync.yml) вернёт битую ссылку.

Тесты покрывают:
1. WIKI.md (committed artifact) не содержит `[PLAN.md]` markdown link.
2. PLAN.md не упоминается даже текстом в футере 'См. также'.
3. tools/build_adr_wiki.py не эмитит PLAN.md в исходниках (root cause guard).
4. End-to-end: прогон build_adr_wiki.py не возвращает PLAN.md в output.

Scope-discipline (Ponytail):
* Только WIKI.md имеет реальную битую markdown-ссылку `[PLAN.md](../../PLAN.md)`.
  63 ADR-файла содержат лишь текстовые упоминания "PLAN.md V22 final" в прозе
  (не clickable, не broken links) — их правка = cross-sprint scope-creep, out of sub-task.
* Соседняя pre-existing broken link `[TECH_DEBT.md](../../../.shared/context/TECH_DEBT.md)`
  (третья `..` лишняя) — отдельный finding, не правится здесь (cross-sprint scope).
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

import pytest

_PROJECT_ROOT = Path(__file__).parents[3]
_WIKI_PATH = _PROJECT_ROOT / "docs" / "adr" / "WIKI.md"
_BUILDER_PATH = _PROJECT_ROOT / "tools" / "build_adr_wiki.py"

# Markdown link pattern: [text](relative/path.md)
_MD_LINK_RE = re.compile(r"\[([^\]]+)\]\(([^)]+)\)")


@pytest.fixture(scope="module")
def wiki_text() -> str:
    """Читает WIKI.md один раз на модуль (shared fixture)."""
    assert _WIKI_PATH.exists(), f"WIKI.md отсутствует: {_WIKI_PATH}"
    return _WIKI_PATH.read_text(encoding="utf-8")


class TestWikiNoBrokenPlanLink:
    """WIKI.md не должен ссылаться на несуществующий PLAN.md."""

    def test_no_plan_md_markdown_link(self, wiki_text: str) -> None:
        """В WIKI.md нет markdown-ссылки на PLAN.md (broken link guard)."""
        bad_links = [
            m.group(0)
            for m in _MD_LINK_RE.finditer(wiki_text)
            if "PLAN.md" in m.group(0)
        ]
        assert not bad_links, (
            f"WIKI.md содержит битую markdown-ссылку на PLAN.md: {bad_links}. "
            "PLAN.md отсутствует в репозитории. Удалите ссылку или укажите существующий файл."
        )

    def test_no_plan_md_textual_mention_in_footer(self, wiki_text: str) -> None:
        """PLAN.md не упоминается даже текстом в футере 'См. также'.

        Текстовые упоминания в prose исторических ADRs остаются (cross-sprint out of scope),
        но футер WIKI.md — auto-generated, должен быть чистым.
        """
        # Изолируем секцию 'См. также' (последний абзац после '## Sprint snapshot')
        footer_match = re.search(
            r"## Sprint snapshot.*?(См\. также:[^\n]*\n(?:[^\n]*\n?)*)\Z",
            wiki_text,
            re.DOTALL,
        )
        assert footer_match is not None, "Секция 'См. также' не найдена в WIKI.md"
        footer = footer_match.group(1)
        assert "PLAN.md" not in footer, (
            f"Футер WIKI.md упоминает PLAN.md:\n{footer}\n"
            "PLAN.md отсутствует — ссылка/mention должна быть удалена."
        )


class TestBuilderScriptNoPlanRef:
    """tools/build_adr_wiki.py не должен эмитить PLAN.md в auto-generated footer."""

    def test_builder_source_has_no_plan_md(self) -> None:
        """Source-guard: build_adr_wiki.py не содержит строку 'PLAN.md'.

        Ловит регрессию до того, как сгенерированный WIKI.md снова станет битым.
        """
        assert _BUILDER_PATH.exists(), f"Скрипт не найден: {_BUILDER_PATH}"
        source = _BUILDER_PATH.read_text(encoding="utf-8")
        assert "PLAN.md" not in source, (
            "tools/build_adr_wiki.py содержит 'PLAN.md' в исходниках — "
            "auto-generated WIKI.md будет содержать битую ссылку при следующем sync. "
            "Удалите PLAN.md из генерируемого футера (см. секцию 'См. также')."
        )

    def test_builder_runs_and_output_has_no_plan_md(self) -> None:
        """End-to-end: запускаем build_adr_wiki.py, проверяем что PLAN.md не появился.

        Subprocess изолирует side-effects (запись WIKI.md) от тестов — скрипт пишет
        в свой нормальный OUT path, после чего мы проверяем результат.
        """
        result = subprocess.run(
            [sys.executable, str(_BUILDER_PATH)],
            check=False,
            capture_output=True,
            text=True,
            cwd=_PROJECT_ROOT,
        )
        assert result.returncode == 0, (
            f"build_adr_wiki.py завершился с ошибкой:\n"
            f"stdout: {result.stdout}\nstderr: {result.stderr}"
        )
        # После прогона скрипт перезаписал WIKI.md — читаем заново и проверяем
        regenerated = _WIKI_PATH.read_text(encoding="utf-8")
        assert "PLAN.md" not in regenerated, (
            "После прогона build_adr_wiki.py WIKI.md содержит 'PLAN.md' — "
            "root-cause fix не сработал."
        )
