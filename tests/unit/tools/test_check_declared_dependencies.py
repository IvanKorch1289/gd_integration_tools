"""TDD: tools/check_declared_dependencies.py — гейт объявленных зависимостей (Wave 13 Q8).

Контекст: пакет ``clickhouse_connect`` использовался в 6 местах ``src/``, но не
был объявлен ни в ``[project].dependencies``, ни в одном extra — только как
mypy-override. Это класс дефекта «висячая зависимость»: импорт есть,
объявления нет.

Проверяет:
* объявленные импорты → exit 0;
* необъявленный пакет → exit 1 (NEW-нарушение);
* пакет из allowlist → не новое нарушение (exit 0);
* ``--update-allowlist`` перегенерирует baseline долга;
* stdlib и модули самого проекта не считаются нарушениями;
* текущее состояние репозитория → exit 0.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tools.check_declared_dependencies import main, normalize_distribution

REPO_ROOT = Path(__file__).resolve().parents[3]

_PYPROJECT = """\
[project]
name = "demo"
version = "0.1.0"
dependencies = [
    "httpx>=0.28.0",
    "pydantic[email]>=2.10.3",
]

[project.optional-dependencies]
db = ["psycopg[binary]>=3.1.0"]
"""


@pytest.fixture
def demo_repo(tmp_path: Path) -> Path:
    """Мини-репозиторий: pyproject.toml + каталог ``src/``."""
    (tmp_path / "pyproject.toml").write_text(_PYPROJECT, encoding="utf-8")
    (tmp_path / "src").mkdir()
    return tmp_path


def _write(root: Path, rel: str, body: str) -> None:
    """Создаёт файл (с промежуточными каталогами) в demo-репозитории."""
    path = root / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(body, encoding="utf-8")


def _run(repo: Path, *extra: str) -> int:
    """Запускает гейт на demo-репозитории."""
    return main(
        [
            "--pyproject",
            str(repo / "pyproject.toml"),
            "--root",
            str(repo / "src"),
            "--allowlist",
            str(repo / "allowlist.txt"),
            *extra,
        ]
    )


class TestDeclaredDependenciesGate:
    """Базовые сценарии гейта."""

    def test_declared_imports_pass(self, demo_repo: Path) -> None:
        """Только объявленные импорты → exit 0."""
        _write(
            demo_repo,
            "src/app.py",
            "import httpx\nfrom pydantic import BaseModel\nimport psycopg\n",
        )
        assert _run(demo_repo) == 0

    def test_undeclared_package_is_new_violation(self, demo_repo: Path) -> None:
        """Необъявленный пакет → exit 1 (новое нарушение)."""
        _write(demo_repo, "src/app.py", "import totally_undeclared_pkg\n")
        assert _run(demo_repo) == 1

    def test_allowlisted_package_is_not_new_violation(self, demo_repo: Path) -> None:
        """Пакет из allowlist — известный долг, не новое нарушение."""
        _write(demo_repo, "src/app.py", "import totally_undeclared_pkg\n")
        (demo_repo / "allowlist.txt").write_text(
            "totally_undeclared_pkg\n", encoding="utf-8"
        )
        assert _run(demo_repo) == 0

    def test_stdlib_and_project_modules_are_ignored(self, demo_repo: Path) -> None:
        """stdlib и модули проекта (``src.*``) — не third-party."""
        _write(
            demo_repo,
            "src/app.py",
            "import json\nimport os\nimport src.backend.core\n"
            "from src.backend.core import config\n",
        )
        assert _run(demo_repo) == 0

    def test_update_allowlist_writes_baseline(self, demo_repo: Path) -> None:
        """``--update-allowlist`` перегенерирует baseline долга."""
        _write(demo_repo, "src/app.py", "import totally_undeclared_pkg\n")
        assert _run(demo_repo, "--update-allowlist") == 0
        allowlist = (demo_repo / "allowlist.txt").read_text(encoding="utf-8")
        assert "totally_undeclared_pkg" in allowlist
        # После перегенерации гейт на том же состоянии — зелёный.
        assert _run(demo_repo) == 0

    def test_json_output_reports_new_violations(
        self, demo_repo: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """JSON-режим отдаёт список новых нарушений."""
        _write(demo_repo, "src/app.py", "import totally_undeclared_pkg\n")
        _run(demo_repo, "--json")
        payload = json.loads(capsys.readouterr().out)
        assert payload["new_violations"] == ["totally_undeclared_pkg"]
        assert payload["total_undeclared"] == 1

    def test_missing_pyproject_is_invocation_error(self, tmp_path: Path) -> None:
        """Нет pyproject.toml → exit 2 (ошибка запуска, не нарушение)."""
        code = main(
            [
                "--pyproject",
                str(tmp_path / "nope.toml"),
                "--root",
                str(tmp_path),
                "--allowlist",
                str(tmp_path / "allowlist.txt"),
            ]
        )
        assert code == 2


class TestNormalization:
    """PEP 503-нормализация имён дистрибутивов."""

    def test_normalize_distribution(self) -> None:
        """Имя дистрибутива приводится к PEP 503-виду."""
        assert normalize_distribution("clickhouse_connect") == "clickhouse-connect"
        assert normalize_distribution("PyYAML") == "pyyaml"
        assert normalize_distribution("python_docx") == "python-docx"


class TestRealRepository:
    """Гейт на текущем состоянии репозитория."""

    def test_repo_has_no_new_violations(self) -> None:
        """Текущий долг — в allowlist, новых нарушений нет (exit 0)."""
        assert main([]) == 0

    def test_allowlist_covers_clickhouse_connect(self) -> None:
        """``clickhouse_connect`` зафиксирован в baseline долга."""
        from tools.check_declared_dependencies import load_allowlist

        assert "clickhouse_connect" in load_allowlist()
