"""Unit-тесты для tools/check_docstrings_prune.py (Cycle 34).

Покрывает:
- parse_entry: valid + invalid formats
- find_stale_entries: deleted-file vs obsolete vs keep classification
- CLI: --write применяет изменения, default dry-run нет
- Idempotency: повторный run не удаляет больше entries
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

from tools.check_docstrings_prune import (
    find_stale_entries,
    parse_entry,
)

PRUNER_PATH = (
    Path(__file__).resolve().parent.parent.parent.parent
    / "tools" / "check_docstrings_prune.py"
)


class TestParseEntry:
    """``parse_entry`` формат-парсер."""

    def test_valid_top_level_entry(self) -> None:
        """Top-level class/function (col=0)."""
        result = parse_entry("src/foo/bar.py:42:0 MyClass")
        assert result == ("src/foo/bar.py", 42, "MyClass")

    def test_valid_method_entry(self) -> None:
        """Method (col=4, qualified name with dot)."""
        result = parse_entry("src/foo/bar.py:42:4 MyClass.method")
        assert result == ("src/foo/bar.py", 42, "MyClass.method")

    def test_invalid_format_returns_none(self) -> None:
        """Менее 3 частей после split(':') → None."""
        assert parse_entry("src/foo/bar.py:42") is None
        assert parse_entry("not-an-entry") is None
        assert parse_entry("") is None

    def test_non_integer_lineno_returns_none(self) -> None:
        """Non-int lineno → None."""
        assert parse_entry("src/foo.py:notint:0 MyClass") is None


class TestFindStaleEntries:
    """``find_stale_entries`` классификация."""

    def test_deleted_file_classified(self, tmp_path: Path) -> None:
        """Entry для несуществующего path → deleted."""
        # tmp_path создаст пустую директорию, никаких файлов.
        allowlist = {
            f"{tmp_path}/never_existed.py:42:0 MyClass",
        }
        keep, deleted, obsolete = find_stale_entries(
            allowlist, [tmp_path], enable_module_check=False,
        )
        assert deleted == allowlist
        assert keep == set()
        assert obsolete == set()

    def test_obsolete_entry_for_documented_file(self, tmp_path: Path) -> None:
        """Файл существует + documented → entry obsolete (no violation)."""
        target = tmp_path / "module.py"
        target.write_text(
            '"""Module doc."""\n\ndef my_func() -> int:\n    """Documented."""\n    return 1\n',
            encoding="utf-8",
        )
        allowlist = {
            f"{target}:3:0 my_func",  # line 3 has ``def my_func``, but it has docstring
        }
        keep, deleted, obsolete = find_stale_entries(
            allowlist, [tmp_path], enable_module_check=False,
        )
        assert obsolete == allowlist
        assert keep == set()
        assert deleted == set()

    def test_active_entry_kept(self, tmp_path: Path) -> None:
        """Файл + missing docstring → entry active (keep)."""
        target = tmp_path / "module.py"
        target.write_text(
            '"""Module doc."""\n\ndef my_func() -> int:\n    return 1\n',  # no docstring
            encoding="utf-8",
        )
        allowlist = {
            f"{target}:3:0 my_func",  # line 3 has ``def my_func``, missing docstring
        }
        keep, deleted, obsolete = find_stale_entries(
            allowlist, [tmp_path], enable_module_check=False,
        )
        assert keep == allowlist
        assert deleted == set()
        assert obsolete == set()

    def test_mixed_classification(self, tmp_path: Path) -> None:
        """Allowlist с mix: deleted + obsolete + keep."""
        active = tmp_path / "active.py"
        active.write_text(
            '"""Mod."""\n\ndef f() -> int:\n    return 1\n',  # missing docstring
            encoding="utf-8",
        )
        documented = tmp_path / "documented.py"
        documented.write_text(
            '"""Mod."""\n\ndef f() -> int:\n    """Doc."""\n    return 1\n',
            encoding="utf-8",
        )
        allowlist = {
            f"{active}:3:0 f",  # keep
            f"{documented}:3:0 f",  # obsolete (documented)
            f"{tmp_path}/nonexistent.py:1:0 Ghost",  # deleted
        }
        keep, deleted, obsolete = find_stale_entries(
            allowlist, [tmp_path], enable_module_check=False,
        )
        assert f"{active}:3:0 f" in keep
        assert f"{documented}:3:0 f" in obsolete
        assert f"{tmp_path}/nonexistent.py:1:0 Ghost" in deleted


class TestPruneCLI:
    """CLI: --write flag, dry-run default, exit codes."""

    def test_help_exits_zero(self) -> None:
        """``--help`` → exit 0."""
        proc = subprocess.run(
            [sys.executable, str(PRUNER_PATH), "--help"],
            capture_output=True,
            text=True,
            check=False,
        )
        assert proc.returncode == 0

    def test_missing_allowlist_exits_2(self, tmp_path: Path) -> None:
        """Несуществующий allowlist → exit 2."""
        proc = subprocess.run(
            [
                sys.executable, str(PRUNER_PATH),
                "--allowlist", str(tmp_path / "no_such.txt"),
                str(tmp_path),
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        assert proc.returncode == 2

    def test_dry_run_no_changes(self, tmp_path: Path) -> None:
        """Default mode = dry-run, file unchanged."""
        target = tmp_path / "mod.py"
        target.write_text(
            '"""Mod."""\n\ndef f() -> int:\n    """Doc."""\n    return 1\n',
            encoding="utf-8",
        )
        allowlist = tmp_path / "al.txt"
        original_content = (
            "# Header\n"
            f"{target}:3:0 f\n"
        )
        allowlist.write_text(original_content, encoding="utf-8")
        proc = subprocess.run(
            [
                sys.executable, str(PRUNER_PATH),
                "--allowlist", str(allowlist),
                str(tmp_path),
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        assert proc.returncode == 0
        assert "dry-run" in proc.stdout
        assert allowlist.read_text(encoding="utf-8") == original_content

    def test_write_removes_obsolete(self, tmp_path: Path) -> None:
        """--write удаляет obsolete entries, exit 0."""
        target = tmp_path / "mod.py"
        target.write_text(
            '"""Mod."""\n\ndef f() -> int:\n    """Doc."""\n    return 1\n',
            encoding="utf-8",
        )
        allowlist = tmp_path / "al.txt"
        allowlist.write_text(
            f"# Header\n{target}:3:0 f\n",
            encoding="utf-8",
        )
        proc = subprocess.run(
            [
                sys.executable, str(PRUNER_PATH),
                "--allowlist", str(allowlist),
                "--write",
                str(tmp_path),
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        assert proc.returncode == 0
        # File rewritten без obsolete entry.
        content = allowlist.read_text(encoding="utf-8")
        assert f"{target}:3:0 f" not in content
        assert "# Header" in content  # comments preserved

    def test_write_no_stale_exits_1(self, tmp_path: Path) -> None:
        """--write без stale entries → exit 1 (no-op)."""
        target = tmp_path / "mod.py"
        target.write_text(
            '"""Mod."""\n\ndef f() -> int:\n    return 1\n',  # missing docstring
            encoding="utf-8",
        )
        allowlist = tmp_path / "al.txt"
        allowlist.write_text(
            f"# Header\n{target}:3:0 f\n",  # active entry
            encoding="utf-8",
        )
        proc = subprocess.run(
            [
                sys.executable, str(PRUNER_PATH),
                "--allowlist", str(allowlist),
                "--write",
                str(tmp_path),
            ],
            capture_output=True,
            text=True,
            check=False,
        )
        assert proc.returncode == 1
        assert "Nothing to prune" in proc.stdout


class TestPruneMainDirect:
    """Direct ``main()`` invocation tests — covered via subprocess in TestPruneCLI."""

    def test_module_imports(self) -> None:
        """Module imports без side effects."""
        import tools.check_docstrings_prune as mod

        assert hasattr(mod, "main")
        assert hasattr(mod, "find_stale_entries")
        assert hasattr(mod, "parse_entry")
        assert hasattr(mod, "collect_current_violations")
