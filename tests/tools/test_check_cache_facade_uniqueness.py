"""Тесты для ``tools/checks/check_cache_facade_uniqueness.py``.

ADR-0352 Stage 1 (cycle 163 cache audit): CI guard предотвращает:

1. Несанкционированные определения ``class UnifiedCacheFacade`` вне
   whitelist (``core/cache/facade.py``, ``services/cache/facade.py``).
2. Потерянные re-exports в ``__all__`` cache-пакетов.
3. Дублирование module-level ``cache_settings`` singleton.

Тесты запускают скрипт на временных файлах и проверяют, что violations
корректно детектятся (positive cases) и clean state не даёт false
positives (negative cases).
"""

from __future__ import annotations

import importlib.util
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
TOOL_PATH = PROJECT_ROOT / "tools" / "checks" / "check_cache_facade_uniqueness.py"


@pytest.fixture()
def module_under_test():
    """Импортирует скрипт как модуль через importlib."""
    spec = importlib.util.spec_from_file_location(
        "check_cache_facade_uniqueness", TOOL_PATH
    )
    assert spec is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    try:
        assert spec.loader is not None
        spec.loader.exec_module(module)
    except Exception:
        sys.modules.pop(spec.name, None)
        raise
    return module


def _run_tool(*args: str) -> subprocess.CompletedProcess[str]:
    """Запускает check как subprocess."""
    return subprocess.run(
        [sys.executable, str(TOOL_PATH), *args],
        capture_output=True,
        text=True,
        cwd=str(PROJECT_ROOT),
        check=False,
    )


class TestImportable:
    def test_script_exists(self) -> None:
        """Скрипт существует по ожидаемому пути."""
        assert TOOL_PATH.exists(), f"Tool not found at {TOOL_PATH}"

    def test_module_imports(self, module_under_test) -> None:
        """Скрипт импортируется без побочных эффектов."""
        assert module_under_test is not None
        assert hasattr(module_under_test, "main")
        assert hasattr(module_under_test, "Report")
        assert hasattr(module_under_test, "Violation")

    def test_clean_state_no_violations(self) -> None:
        """Запуск на текущем дереве → exit 0 (CLEAN state)."""
        result = _run_tool("--strict")
        assert result.returncode == 0, (
            f"Unexpected violations:\n{result.stdout}\n{result.stderr}"
        )
        assert "CLEAN" in result.stdout

    def test_json_mode(self) -> None:
        """JSON mode выводит валидный JSON."""
        import json

        result = _run_tool("--json")
        assert result.returncode == 0
        data = json.loads(result.stdout)
        assert "files_scanned" in data
        assert "violations" in data
        assert "clean" in data
        assert data["clean"] is True


class TestDetectsUnauthorizedDefinition:
    def test_unauthorized_class_caught(self) -> None:
        """Создаём временный файл с class UnifiedCacheFacade вне whitelist."""
        fixture = (
            PROJECT_ROOT
            / "src"
            / "backend"
            / "_test_cache_violation_fixture.py"
        )
        fixture.write_text(
            '"""Test fixture."""\n'
            "\n"
            "class UnifiedCacheFacade:\n"
            "    pass\n",
            encoding="utf-8",
        )
        try:
            result = _run_tool("--strict")
            assert result.returncode == 1, (
                "Expected violation but got clean state. "
                f"stdout: {result.stdout}"
            )
            assert "unauthorized_definition" in result.stdout
            assert "_test_cache_violation_fixture.py" in result.stdout
        finally:
            fixture.unlink()

    def test_whitelisted_files_clean(self) -> None:
        """Whitelisted файлы не trigger'ятся."""
        # core/cache/facade.py + services/cache/facade.py — это whitelist.
        # Если что-то в них сломает AST — тест упадёт.
        result = _run_tool("--strict")
        # Если сам whitelist работает, мы не должны видеть эти файлы
        # в violations.
        assert (
            "core/cache/facade.py:" not in result.stdout
            or "CLEAN" in result.stdout
        )


class TestDetectsMissingReexport:
    def test_missing_reexport_caught(self) -> None:
        """Меняем services/cache/__init__.py — убираем UnifiedCacheFacade."""
        init_path = (
            PROJECT_ROOT
            / "src"
            / "backend"
            / "services"
            / "cache"
            / "__init__.py"
        )
        backup = init_path.read_text(encoding="utf-8")
        # Strip UnifiedCacheFacade из __all__.
        bad_content = '"""Cache services package."""\n__all__ = ("get_unified_cache_facade",)\n'
        try:
            init_path.write_text(bad_content, encoding="utf-8")
            result = _run_tool("--strict")
            assert result.returncode == 1
            assert "missing_reexport" in result.stdout
            assert "services/cache/__init__.py" in result.stdout
        finally:
            init_path.write_text(backup, encoding="utf-8")

    def test_restored_reexport_clean(self) -> None:
        """После восстановления __all__ — clean."""
        # Без изменений — должно быть clean.
        result = _run_tool("--strict")
        assert result.returncode == 0


class TestDetectsUnauthorizedSingleton:
    def test_unauthorized_singleton_caught(self) -> None:
        """Создаём файл с module-level cache_settings вне whitelist."""
        fixture = (
            PROJECT_ROOT
            / "src"
            / "backend"
            / "_test_cache_settings_violation.py"
        )
        fixture.write_text(
            '"""Test fixture."""\n'
            "\n"
            "class _Fake:\n"
            "    pass\n"
            "\n"
            "cache_settings = _Fake()\n",
            encoding="utf-8",
        )
        try:
            result = _run_tool("--strict")
            assert result.returncode == 1
            assert "unauthorized_settings_singleton" in result.stdout
        finally:
            fixture.unlink()


class TestReportDataClass:
    def test_violation_serialization(self, module_under_test) -> None:
        """Violation.to_dict() возвращает JSON-friendly dict."""
        v = module_under_test.Violation(
            kind="test_kind",
            file="test.py",
            line=42,
            message="test message",
            snippet="snippet",
        )
        d = v.to_dict()
        assert d["kind"] == "test_kind"
        assert d["file"] == "test.py"
        assert d["line"] == 42
        assert d["message"] == "test message"
        assert d["snippet"] == "snippet"

    def test_report_is_clean_initially(self, module_under_test) -> None:
        """Report() создаётся clean."""
        report = module_under_test.Report()
        assert report.is_clean() is True
        assert len(report.violations) == 0


class TestExtractAllNames:
    def test_simple_list(self, module_under_test) -> None:
        """Извлекает имена из ``__all__ = ('a', 'b')``."""
        import ast

        tree = ast.parse('__all__ = ("a", "b", "c")\n')
        names = module_under_test._extract_all_names(tree)
        assert names == {"a", "b", "c"}

    def test_tuple(self, module_under_test) -> None:
        """Извлекает имена из tuple __all__."""
        import ast

        tree = ast.parse('__all__ = ("a", "b")\n')
        names = module_under_test._extract_all_names(tree)
        assert names == {"a", "b"}

    def test_empty_when_no_all(self, module_under_test) -> None:
        """Без __all__ возвращает пустой set."""
        import ast

        tree = ast.parse("x = 1\n")
        names = module_under_test._extract_all_names(tree)
        assert names == set()