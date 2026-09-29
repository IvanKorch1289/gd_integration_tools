"""Sprint 4 (partial) — characterization test для layer violations baseline.

TDD principle applied: tests describe the current state explicitly.
Refactor toward target count (167 → ~140) — multi-sprint effort.

This test FAILS if:
- New layer violations are added (drift detection)
- Allowlist is modified without justification

Tests do NOT enforce removal of violations — только freeze baseline +
detect drift. Real reduction — multi-sprint work per
MULTI_SPRINT_2026-08-17.md Sprint 4 roadmap.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
ALLOWLIST_FILE = REPO_ROOT / "tools" / "check_layers_allowlist.txt"

# Верхняя граница legacy-нарушений, зафиксированная в Phase 0
# (MULTI_SPRINT_2026-08-17.md, Sprint 4). Канонический закон проекта:
# allowlist может только УМЕНЬШАТЬСЯ. Поэтому ниже тесты — не «фотография»
# текущего числа, а рэтчеты: рост относительно этой границы — регресс,
# уменьшение — ожидаемый прогресс.
LEGACY_HIGH_WATER_MARK = 167

# Максимум записей в allowlist: страховка от бесконтрольного роста файла.
ALLOWLIST_MAX_ENTRIES = 250


def _run_check_layers() -> subprocess.CompletedProcess[str]:
    """Run ``tools/check_layers.py`` and capture output.

    Используется ``sys.executable``, а не ``python`` из PATH: проект живёт на
    Python 3.14, где PEP 758 допускает ``except A, B:`` без скобок. Системный
    ``python`` — 3.12, такой синтаксис не парсится, и гейт fail-closed
    сообщал о 163 «непарсящихся» файлах и exit 3, хотя проект полностью
    корректен. Тест обязан запускать гейт тем же интерпретатором, что и
    ``make layers``.
    """
    return subprocess.run(
        [sys.executable, "tools/check_layers.py"],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=300,
    )


def _reported_legacy_count(output: str) -> int | None:
    """Извлечь число legacy-нарушений из вывода гейта (``baseline: N legacy``)."""
    match = re.search(r"baseline:\s*(\d+)\s*legacy", output)
    return int(match.group(1)) if match else None


class TestLayerViolationsBaseline:
    """Freeze current state — drift detection."""

    def test_allowlist_file_exists(self) -> None:
        assert ALLOWLIST_FILE.exists(), (
            f"Allowlist file not found: {ALLOWLIST_FILE}. "
            f"Migration: re-run check_layers.py --update-allowlist."
        )

    def test_check_layers_runs_clean(self) -> None:
        """check_layers.py MUST exit 0 (no new violations)."""
        result = _run_check_layers()
        assert result.returncode == 0, (
            f"check_layers.py failed (exit {result.returncode}). "
            f"Output:\n{result.stdout}\n{result.stderr}"
        )

    def test_check_layers_reports_zero_new(self) -> None:
        """Output should say '0 новых' (zero new violations)."""
        result = _run_check_layers()
        assert "0 новых" in result.stdout or "0 new" in result.stdout, (
            f"check_layers.py output changed format. "
            f"Expected '0 новых' or '0 new'. Output:\n{result.stdout}"
        )

    def test_baseline_legacy_violations_documented(self) -> None:
        """Legacy-baseline не должна ВЫРАСТИ относительно Phase 0 (167).

        Раньше здесь было жёсткое ``assert "baseline: 167"``, то есть
        «фотография» числа. После того как allowlist сократили до 22,
        тест падал на законном уменьшении — поощряя обратное движение.
        Теперь проверяется сам закон проекта: baseline может только
        уменьшаться. Рост — регресс; уменьшение — ожидаемый прогресс.
        """
        result = _run_check_layers()
        reported = _reported_legacy_count(result.stdout)
        assert reported is not None, (
            f"Не удалось распознать 'baseline: N legacy' в выводе гейта. "
            f"Формат вывода изменился?\n{result.stdout}"
        )
        assert reported <= LEGACY_HIGH_WATER_MARK, (
            f"Legacy baseline выросла: {reported} > {LEGACY_HIGH_WATER_MARK} "
            f"(Phase 0). Allowlist может только уменьшаться. "
            f"Вывод:\n{result.stdout}"
        )


class TestLayerViolationsCountReduction:
    """Target: 167 → 140 (Sprint 4 roadmap). Multi-sprint effort."""

    def test_target_baseline_documented(self) -> None:
        """Roadmap target должен быть в MULTI_SPRINT_2026-08-17.md."""
        roadmap = REPO_ROOT / "docs" / "audit" / "MULTI_SPRINT_2026-08-17.md"
        assert roadmap.exists(), f"Roadmap file not found: {roadmap}"

        content = roadmap.read_text()
        # Sprint 4 target: 167 → 140
        assert "167" in content, (
            "MULTI_SPRINT_2026-08-17.md не содержит baseline reference (167)"
        )
        assert "140" in content, (
            "MULTI_SPRINT_2026-08-17.md не содержит Sprint 4 target (140)"
        )


class TestAllowlistFormat:
    """Allowlist format validation — prevent corruption."""

    def test_allowlist_has_header(self) -> None:
        lines = ALLOWLIST_FILE.read_text().splitlines()
        assert lines[0].startswith("#"), (
            f"Allowlist должен начинаться с header комментария. "
            f"First line: {lines[0]!r}"
        )

    def test_allowlist_entries_have_three_columns(self) -> None:
        """Each entry: <rel_path>\\t<layer>\\t<module>."""
        lines = ALLOWLIST_FILE.read_text().splitlines()
        bad_lines = [
            (i + 1, line)
            for i, line in enumerate(lines)
            if line and not line.startswith("#") and line.count("\t") != 2
        ]
        assert not bad_lines, (
            f"Allowlist entries должны иметь 3 колонки (tab-separated). "
            f"Bad lines:\n{bad_lines[:5]}"
        )

    def test_allowlist_entry_count_reasonable(self) -> None:
        """Allowlist не должен расти без границ — рэтчет только сверху.

        Раньше диапазон был ``50 <= count <= 250``, то есть тест ПРОКАЗЫВАЛ
        при слишком малом числе записей. Это инвертировало закон проекта
        («allowlist можно только уменьшать»): идеальное состояние —
        ноль legacy-нарушений — считалось бы провалом. Нижняя граница
        убрана, верхняя сохранена.
        """
        lines = ALLOWLIST_FILE.read_text().splitlines()
        entry_count = sum(1 for line in lines if line and not line.startswith("#"))
        assert entry_count <= ALLOWLIST_MAX_ENTRIES, (
            f"Allowlist entry count {entry_count} превысил максимум "
            f"{ALLOWLIST_MAX_ENTRIES}. Рассмотрите устранение нарушений "
            f"вместо их легализации."
        )
