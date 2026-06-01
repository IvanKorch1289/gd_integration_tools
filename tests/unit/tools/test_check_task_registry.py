# ruff: noqa: S101
"""Тесты CI-gate ``tools/checks/check_task_registry.py``.

Покрывают:

* detection ``asyncio.create_task`` / ``asyncio.ensure_future`` /
  ``loop.create_task`` / ``loop.ensure_future``;
* игнорирование ``if __name__ == "__main__":`` блоков;
* игнорирование ``# noqa: orphan-create-task`` маркера;
* отсутствие false positives на ``get_task_registry().create_task(...)``.
"""

from __future__ import annotations

import sys
from pathlib import Path
from textwrap import dedent

_TOOLS = Path(__file__).resolve().parents[3] / "tools"
sys.path.insert(0, str(_TOOLS))

from checks.check_task_registry import RULE_ORPHAN_TASK, check_file  # noqa: E402


def _write(tmp: Path, name: str, body: str) -> Path:
    path = tmp / name
    path.write_text(dedent(body).lstrip(), encoding="utf-8")
    return path


class TestCheckTaskRegistry:
    """CI-gate orphan-create-task сценарии."""

    def test_clean_file_returns_no_violations(self, tmp_path: Path) -> None:
        path = _write(
            tmp_path,
            "clean.py",
            """
            import asyncio

            async def main():
                from src.backend.core.utils.task_registry import (
                    get_task_registry,
                )
                get_task_registry().create_task(worker(), name="ok")
            """,
        )
        violations = check_file(path)
        assert violations == []

    def test_asyncio_create_task_detected(self, tmp_path: Path) -> None:
        path = _write(
            tmp_path,
            "orphan.py",
            """
            import asyncio

            async def main():
                asyncio.create_task(worker())
            """,
        )
        violations = check_file(path)
        assert len(violations) == 1
        assert violations[0].rule == RULE_ORPHAN_TASK
        assert violations[0].call == "asyncio.create_task"

    def test_asyncio_ensure_future_detected(self, tmp_path: Path) -> None:
        path = _write(
            tmp_path,
            "ensure_future.py",
            """
            import asyncio

            async def main():
                asyncio.ensure_future(worker())
            """,
        )
        violations = check_file(path)
        assert len(violations) == 1
        assert violations[0].call == "asyncio.ensure_future"

    def test_loop_create_task_detected(self, tmp_path: Path) -> None:
        path = _write(
            tmp_path,
            "loop_create.py",
            """
            import asyncio

            async def main():
                loop = asyncio.get_event_loop()
                loop.create_task(worker())
            """,
        )
        violations = check_file(path)
        assert len(violations) == 1
        assert violations[0].call == "loop.create_task"

    def test_selftest_block_ignored(self, tmp_path: Path) -> None:
        """Блок ``if __name__ == "__main__":`` не считается нарушением."""
        path = _write(
            tmp_path,
            "main_guard.py",
            """
            import asyncio

            async def worker(): ...

            if __name__ == "__main__":
                asyncio.create_task(worker())
            """,
        )
        violations = check_file(path)
        assert violations == []

    def test_noqa_marker_ignored(self, tmp_path: Path) -> None:
        """Inline ``# noqa: orphan-create-task`` маркер пропускает строку."""
        path = _write(
            tmp_path,
            "noqa.py",
            """
            import asyncio

            async def worker(): ...

            async def main():
                asyncio.create_task(worker())  # noqa: orphan-create-task
            """,
        )
        violations = check_file(path)
        assert violations == []

    def test_multiple_violations_in_same_file(self, tmp_path: Path) -> None:
        path = _write(
            tmp_path,
            "multi.py",
            """
            import asyncio

            async def worker(): ...

            async def a():
                asyncio.create_task(worker())

            async def b():
                asyncio.ensure_future(worker())
            """,
        )
        violations = check_file(path)
        assert len(violations) == 2
        calls = {v.call for v in violations}
        assert calls == {"asyncio.create_task", "asyncio.ensure_future"}
