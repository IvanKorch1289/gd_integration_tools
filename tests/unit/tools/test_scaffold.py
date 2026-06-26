"""TDD: tools/scaffold.py — правильные пути (M14.3 fix).

Scaffold СОЗДАЁТ файлы в ``src/dsl/...`` (без backend), но реальная
архитектура — ``src/backend/dsl/...``. Нужно:
1. Fix scaffold.py — добавить "backend" в пути
2. Или удалить scaffold (Ponytail: dry-run должен быть tested)

M14.3: fix path bug.
"""
# ruff: noqa: S101
from __future__ import annotations

from pathlib import Path
import subprocess


class TestScaffoldPaths:
    def test_processor_path_includes_backend(self) -> None:
        """Scaffold processor создаёт файл в src/backend/dsl/..."""
        result = subprocess.run(
            ["python", "tools/scaffold.py", "processor",
             "--name", "TestProc", "--module", "testproc", "--dry-run"],
            capture_output=True, text=True, cwd="/home/user/dev/gd_integration_tools"
        )
        # dry-run output должен указывать правильный путь
        assert "src/backend/dsl/engine/processors/testproc.py" in result.stdout, (
            f"Scaffold должен создавать в src/backend/dsl/, "
            f"но получил: {result.stdout!r}"
        )
        # Negative check: НЕ должно быть src/dsl/ (без backend)
        assert "src/dsl/engine/processors/testproc.py" not in result.stdout, (
            "Scaffold создаёт в неправильном пути (без backend)"
        )

    def test_route_path_includes_backend(self) -> None:
        """Scaffold route создаёт файл в src/backend/dsl/..."""
        result = subprocess.run(
            ["python", "tools/scaffold.py", "route",
             "--name", "test.demo", "--dry-run"],
            capture_output=True, text=True, cwd="/home/user/dev/gd_integration_tools"
        )
        assert "src/backend/dsl/routes/test_demo.py" in result.stdout, (
            f"Scaffold route должен создавать в src/backend/dsl/, "
            f"но получил: {result.stdout!r}"
        )
