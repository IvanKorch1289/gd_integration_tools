"""Тесты fail-closed AST-гейта ``check_python3_syntax`` (ADR-0304).

Гейт требует: каждый ``.py`` обязан разбираться ``ast.parse``.
Форма ``except A, B:`` без скобок канонична (PEP 758) и гейтом
не флагается; реальный хазард ``except A, B as e:`` — SyntaxError.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

GATE = (
    Path(__file__).resolve().parents[3] / "tools" / "checks" / "check_python3_syntax.py"
)


def _run(root: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(GATE), "--root", str(root), "--json"],
        capture_output=True,
        text=True,
        timeout=60,
    )


class TestParseGate:
    def test_clean_file_passes(self, tmp_path: Path) -> None:
        """Валидный файл — 0 нарушений, exit 0."""
        (tmp_path / "ok.py").write_text(
            "try:\n    pass\nexcept (ValueError, TypeError):\n    pass\n",
            encoding="utf-8",
        )
        r = _run(tmp_path)
        assert r.returncode == 0
        assert r.stdout.strip() == "[]"

    def test_canonical_pep758_form_passes(self, tmp_path: Path) -> None:
        """Каноничная форма ``except A, B:`` без скобок (PEP 758) — не нарушение."""
        (tmp_path / "canon.py").write_text(
            "try:\n    pass\nexcept ValueError, TypeError:\n    pass\n",
            encoding="utf-8",
        )
        r = _run(tmp_path)
        assert r.returncode == 0

    def test_parse_failure_detected_fail_closed(self, tmp_path: Path) -> None:
        """SyntaxError (в т.ч. ``except A, B as e:``) — нарушение, exit 1."""
        (tmp_path / "bad.py").write_text(
            "def f():\n    try:\n        pass\n    except A, B as e:\n        pass\n",
            encoding="utf-8",
        )
        r = _run(tmp_path)
        assert r.returncode == 1
        assert "syntax-parse-failed" in r.stdout
        assert "bad.py" in r.stdout

    def test_unparseable_syntax_error_fails_closed(self, tmp_path: Path) -> None:
        """Произвольный непарсящийся файл — нарушение."""
        (tmp_path / "broken.py").write_text("def f(:\n", encoding="utf-8")
        r = _run(tmp_path)
        assert r.returncode == 1
