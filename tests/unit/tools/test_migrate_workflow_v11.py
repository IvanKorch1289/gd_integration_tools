# ruff: noqa: S101
"""Unit-тесты `tools/migrate_workflow_v11.py` (Wave D.3)."""

from __future__ import annotations

import sys
from pathlib import Path
from textwrap import dedent

import pytest

# tools/ — CLI-скрипты, не пакет: добавляем в sys.path.
_TOOLS = Path(__file__).resolve().parents[3] / "tools"
sys.path.insert(0, str(_TOOLS))

from migrate_workflow_v11 import scan_file  # noqa: E402


def _write(tmp: Path, name: str, body: str) -> Path:
    file = tmp / name
    file.write_text(dedent(body), encoding="utf-8")
    return file


class TestScanFile:
    def test_clean_file_no_findings(self, tmp_path: Path) -> None:
        path = _write(
            tmp_path,
            "clean.py",
            """
            from typing import Any

            def pure(x: Any) -> Any:
                return x + 1
            """,
        )
        assert scan_file(path) == []

    def test_detects_random_uuid_datetime(self, tmp_path: Path) -> None:
        path = _write(
            tmp_path,
            "bad.py",
            """
            import random
            import uuid
            from datetime import datetime

            def step():
                _ = random.random()
                _ = uuid.uuid4()
                _ = datetime.utcnow()
            """,
        )
        findings = scan_file(path)
        rules = {f.rule for f in findings}
        assert rules == {"non-deterministic-call"}
        messages = " ".join(f.message for f in findings)
        assert "random.random" in messages
        assert "uuid.uuid4" in messages
        assert "datetime.utcnow" in messages

    def test_detects_forbidden_imports(self, tmp_path: Path) -> None:
        path = _write(
            tmp_path,
            "threads.py",
            """
            import threading
            import multiprocessing
            """,
        )
        findings = scan_file(path)
        assert {f.rule for f in findings} == {"forbidden-import"}
        assert len(findings) == 2

    def test_detects_io_imports(self, tmp_path: Path) -> None:
        path = _write(
            tmp_path,
            "io.py",
            """
            import requests
            from sqlalchemy import select
            """,
        )
        findings = scan_file(path)
        assert {f.rule for f in findings} == {"io-import"}
        assert len(findings) == 2

    def test_syntax_error_is_finding(self, tmp_path: Path) -> None:
        path = _write(tmp_path, "broken.py", "def x(:\n")
        findings = scan_file(path)
        assert len(findings) == 1
        assert findings[0].rule == "syntax-error"

    def test_non_python_returns_empty(self, tmp_path: Path) -> None:
        path = tmp_path / "data.txt"
        path.write_text("hello", encoding="utf-8")
        assert scan_file(path) == []


class TestMainCli:
    def test_strict_mode_returns_1_when_findings(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        from migrate_workflow_v11 import main

        path = _write(
            tmp_path,
            "bad.py",
            """
            import random
            x = random.random()
            """,
        )
        rc = main([str(path), "--strict"])
        assert rc == 1
        captured = capsys.readouterr()
        assert "random.random" in captured.out

    def test_no_findings_returns_0(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        from migrate_workflow_v11 import main

        path = _write(tmp_path, "ok.py", "x = 1\n")
        rc = main([str(path), "--strict"])
        assert rc == 0

    def test_json_emits_structured_report(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        import json as _json

        from migrate_workflow_v11 import main

        path = _write(
            tmp_path,
            "bad.py",
            """
            import random
            x = random.random()
            """,
        )
        rc = main([str(path), "--json"])
        assert rc == 0
        captured = capsys.readouterr()
        report = _json.loads(captured.out)
        assert report["summary"]["findings"] == 1
        assert report["summary"]["by_rule"] == {"non-deterministic-call": 1}
