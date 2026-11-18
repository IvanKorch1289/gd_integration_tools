"""Тесты ``tools/changelog_autogen.py``.

Регресс: ``make release-notes`` (make/quickwins.mk) ссылался на
``tools/changelog_autogen.py``, которого в репозитории не было — цель всегда
падала с «No such file or directory». Каноническая реализация добавлена
вместе с этим набором тестов.
"""

from __future__ import annotations

import importlib.util
import subprocess
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit

PROJECT_ROOT = Path(__file__).resolve().parents[3]
SCRIPT = PROJECT_ROOT / "tools" / "changelog_autogen.py"

_spec = importlib.util.spec_from_file_location("changelog_autogen", SCRIPT)
assert _spec is not None and _spec.loader is not None
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)

parse_commit = _mod.parse_commit
build_release_notes = _mod.build_release_notes


class TestParseCommit:
    """Разбор Conventional Commit."""

    @pytest.mark.parametrize(
        ("subject", "expected"),
        [
            ("feat: добавить гейт", ("feat", None, "добавить гейт", False)),
            ("fix(core): починить кэш", ("fix", "core", "починить кэш", False)),
            (
                "feat(api)!: сломанный контракт",
                ("feat", "api", "сломанный контракт", True),
            ),
            ("chore: рутина", ("chore", None, "рутина", False)),
        ],
    )
    def test_standard_subjects(
        self, subject: str, expected: tuple[str, str | None, str, bool]
    ) -> None:
        """Стандартные формы разбираются по Conventional Commits."""
        assert parse_commit(subject) == expected

    def test_non_conventional_subject(self) -> None:
        """Нестандартный subject попадает в группу «Прочее»."""
        ctype, scope, text, breaking = parse_commit("просто коммит")

        assert ctype == "other"
        assert scope is None
        assert text == "просто коммит"
        assert breaking is False


class TestBuildReleaseNotes:
    """Сборка markdown-отчёта."""

    def test_groups_are_ordered(self) -> None:
        """Группы выводятся в фиксированном порядке (feat раньше fix)."""
        notes = build_release_notes(["fix: a", "feat: b", "docs: c"])

        assert notes.index("Новые возможности") < notes.index("Исправления")
        assert notes.index("Исправления") < notes.index("Документация")

    def test_entries_keep_scope_and_breaking_marker(self) -> None:
        """Scope и BREAKING-маркер попадают в вывод."""
        notes = build_release_notes(["feat(api)!: новый контракт"])

        assert "(api)" in notes
        assert "**BREAKING**" in notes

    def test_empty_input(self) -> None:
        """Пустой диапазон даёт явный текст, а не пустой файл."""
        notes = build_release_notes([])

        assert "Нет коммитов" in notes

    def test_output_is_deterministic(self) -> None:
        """Один и тот же вход даёт побайтово одинаковый вывод."""
        subjects = ["feat: a", "fix: b"]

        assert build_release_notes(subjects) == build_release_notes(subjects)


class TestCli:
    """CLI работает на реальном git-репозитории."""

    def test_script_exists(self) -> None:
        """Файл, на который ссылается make-цель, существует."""
        assert SCRIPT.is_file()

    def test_make_target_reference_resolves(self) -> None:
        """Все ``tools/*.py``, упомянутые в make-целях, существуют."""
        import re

        missing: list[str] = []
        for mk in sorted((PROJECT_ROOT / "make").glob("*.mk")):
            for ref in re.findall(
                r"tools/[A-Za-z0-9_/.-]+\.py", mk.read_text(encoding="utf-8")
            ):
                if not (PROJECT_ROOT / ref).is_file():
                    missing.append(f"{mk.name}: {ref}")

        assert not missing, missing

    def test_cli_writes_output_file(self, tmp_path: Path) -> None:
        """CLI пишет отчёт в файл и возвращает exit 0."""
        out = tmp_path / "notes.md"
        proc = subprocess.run(
            [
                str(PROJECT_ROOT / ".venv" / "bin" / "python"),
                str(SCRIPT),
                "--from",
                "HEAD~3",
                "--output",
                str(out),
            ],
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            check=False,
        )

        assert proc.returncode == 0, proc.stderr
        assert out.is_file()
        assert out.read_text(encoding="utf-8").startswith("# Release notes")

    def test_cli_rejects_bad_ref(self, tmp_path: Path) -> None:
        """Несуществующий ref → exit 1 с сообщением, а не traceback."""
        proc = subprocess.run(
            [
                str(PROJECT_ROOT / ".venv" / "bin" / "python"),
                str(SCRIPT),
                "--from",
                "no-such-ref-xyz",
            ],
            cwd=PROJECT_ROOT,
            capture_output=True,
            text=True,
            check=False,
        )

        assert proc.returncode == 1
        assert "ERROR" in proc.stderr
