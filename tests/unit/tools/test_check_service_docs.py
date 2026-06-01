"""Smoke-тесты для check_service_docs.py.

Запускают скрипт как subprocess (как test_supply_chain_scaffold.py),
поскольку ``tools/`` не входит в pythonpath проекта.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

_ROOT = Path(__file__).parent.parent.parent.parent
_SCRIPT = _ROOT / "tools" / "checks" / "check_service_docs.py"


def test_script_exists() -> None:
    """Файл tools/checks/check_service_docs.py существует."""
    assert _SCRIPT.exists()


def test_script_returns_zero_on_good_fixture(tmp_path: Path) -> None:
    """Скрипт возвращает exit 0, если все @service_dsl документированы."""
    good = tmp_path / "good_service.py"
    good.write_text(
        "from somewhere import service_dsl\n"
        "\n"
        "@service_dsl(crud=True)\n"
        "class GoodService:\n"
        '    """Хороший сервис с описанием более 20 символов.\n'
        "\n"
        "    Пример::\n"
        "\n"
        "        GoodService().do_it()\n"
        '    """\n'
        "    pass\n",
        encoding="utf-8",
    )

    result = subprocess.run(
        [sys.executable, str(_SCRIPT), "--target", str(tmp_path)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_script_returns_one_on_bad_fixture(tmp_path: Path) -> None:
    """Скрипт возвращает exit 1 если есть нарушения в @service_dsl."""
    bad = tmp_path / "bad_service.py"
    bad.write_text(
        "from somewhere import service_dsl\n"
        "\n"
        "@service_dsl\n"
        "class BadService:\n"
        '    """TODO"""\n'
        "    pass\n",
        encoding="utf-8",
    )

    result = subprocess.run(
        [sys.executable, str(_SCRIPT), "--target", str(tmp_path)],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 1, result.stdout + result.stderr
    assert "TODO" in result.stdout or "FAIL" in result.stdout


def test_script_runs_against_real_codebase() -> None:
    """Smoke: скрипт запускается на src/backend/services без crash."""
    result = subprocess.run(
        [sys.executable, str(_SCRIPT), "--target", str(_ROOT / "src" / "backend" / "services")],
        capture_output=True,
        text=True,
        check=False,
    )
    # exit-code не важен (могут быть нарушения), важно что скрипт работает.
    assert result.returncode in (0, 1), result.stdout + result.stderr
    assert "Проверено" in result.stdout
