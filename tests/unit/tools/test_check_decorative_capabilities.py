"""TDD: tools/check_decorative_capabilities.py — гейт S-18 (Wave 13 Q15).

Проверяет класс дефекта: непустая ``capabilities=`` в ``@processor`` должна
сопровождаться работающим ``required_capability``. Иначе декларация попадает
только в JSON-схему/LSP, но не проверяется в рантайме.

Сценарии:
* чистый набор → нет нарушений;
* декоративная декларация → обнаружена;
* ``required_capability`` → не декоративная;
* allowlist → известный долг, не новое нарушение;
* ``--update-allowlist`` → пересоздаёт baseline;
* текущий репозиторий → 0 новых нарушений.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from tools.check_decorative_capabilities import main, scan_tree

REPO_ROOT = Path(__file__).resolve().parents[3]


@pytest.fixture
def demo_repo(tmp_path: Path) -> Path:
    """Мини-репозиторий с одним модулем процессоров."""
    source_dir = tmp_path / "src"
    source_dir.mkdir()
    return tmp_path


def _write_processors(repo: Path, body: str) -> None:
    """Записывает исходник процессоров в demo-репозиторий."""
    (repo / "src" / "processors.py").write_text(body, encoding="utf-8")


def _run(repo: Path, *extra: str) -> int:
    """Запускает гейт на demo-репозитории."""
    return main(
        [
            "--root",
            str(repo / "src"),
            "--allowlist",
            str(repo / "allowlist.txt"),
            *extra,
        ]
    )


class TestDecorativeCapabilitiesGate:
    """Базовые сценарии AST-гейта."""

    def test_clean_set_has_no_violations(self, demo_repo: Path) -> None:
        """Процессор без capability-декларации не считается декоративным."""
        _write_processors(
            demo_repo, '@processor("plain")\nclass PlainProcessor:\n    pass\n'
        )
        assert scan_tree([demo_repo / "src"]) == []
        assert _run(demo_repo, "--ci") == 0

    def test_nonempty_capabilities_without_required_is_decorative(
        self, demo_repo: Path
    ) -> None:
        """``capabilities=`` без ``required_capability`` — декоративная декларация."""
        _write_processors(
            demo_repo,
            '@processor("decorative", capabilities=("x.y",))\n'
            "class DecorativeProcessor:\n"
            "    pass\n",
        )
        declarations = scan_tree([demo_repo / "src"])
        assert len(declarations) == 1
        assert declarations[0].class_name == "DecorativeProcessor"
        assert declarations[0].capabilities == ("x.y",)
        assert declarations[0].key == "src/processors.py::DecorativeProcessor"
        assert _run(demo_repo, "--ci") == 1

    def test_processor_import_alias_is_detected(self, demo_repo: Path) -> None:
        """Alias импорта registry.processor не скрывает декоративную декларацию."""
        _write_processors(
            demo_repo,
            "from src.backend.dsl.registry import processor as register_processor\n"
            '@register_processor("decorative", capabilities=("x.y",))\n'
            "class DecorativeProcessor:\n"
            "    pass\n",
        )
        assert len(scan_tree([demo_repo / "src"])) == 1
        assert _run(demo_repo, "--ci") == 1

    def test_required_capability_is_not_decorative(self, demo_repo: Path) -> None:
        """Непустой ``required_capability`` означает работающий runtime-гейт."""
        _write_processors(
            demo_repo,
            '@processor("enforced", capabilities=("x.y",))\n'
            "class EnforcedProcessor:\n"
            '    required_capability: ClassVar[str | None] = "x.y"\n',
        )
        assert scan_tree([demo_repo / "src"]) == []
        assert _run(demo_repo, "--ci") == 0

    def test_required_capability_none_is_decorative(self, demo_repo: Path) -> None:
        """Явный ``required_capability = None`` не включает runtime-гейт."""
        _write_processors(
            demo_repo,
            '@processor("decorative", capabilities=("x.y",))\n'
            "class DecorativeProcessor:\n"
            "    required_capability: ClassVar[str | None] = None\n",
        )
        assert len(scan_tree([demo_repo / "src"])) == 1
        assert _run(demo_repo, "--ci") == 1

    def test_allowlisted_declaration_is_not_new_violation(
        self, demo_repo: Path
    ) -> None:
        """Запись в allowlist означает известный долг, а не новое нарушение."""
        _write_processors(
            demo_repo,
            '@processor("decorative", capabilities=("x.y",))\n'
            "class DecorativeProcessor:\n"
            "    pass\n",
        )
        (demo_repo / "allowlist.txt").write_text(
            "src/processors.py::DecorativeProcessor  # owner=dsl | reason=baseline\n",
            encoding="utf-8",
        )
        assert _run(demo_repo, "--ci") == 0

    def test_update_allowlist_writes_baseline(self, demo_repo: Path) -> None:
        """``--update-allowlist`` перегенерирует baseline фактического долга."""
        _write_processors(
            demo_repo,
            '@processor("decorative", capabilities=("x.y",))\n'
            "class DecorativeProcessor:\n"
            "    pass\n",
        )
        assert _run(demo_repo, "--update-allowlist") == 0
        allowlist = (demo_repo / "allowlist.txt").read_text(encoding="utf-8")
        assert "src/processors.py::DecorativeProcessor" in allowlist
        assert "owner=dsl" in allowlist
        assert _run(demo_repo, "--ci") == 0

    def test_json_output_reports_new_violations(
        self, demo_repo: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        """JSON-режим перечисляет новые нарушения и сохраняет exit code 1."""
        _write_processors(
            demo_repo,
            '@processor("decorative", capabilities=("x.y",))\n'
            "class DecorativeProcessor:\n"
            "    pass\n",
        )
        assert _run(demo_repo, "--ci", "--json") == 1
        payload = json.loads(capsys.readouterr().out)
        assert payload["total_decorative"] == 1
        assert payload["new_violations"] == [
            {
                "path": "src/processors.py",
                "lineno": 1,
                "class_name": "DecorativeProcessor",
                "capabilities": ["x.y"],
                "key": "src/processors.py::DecorativeProcessor",
            }
        ]


class TestRealRepository:
    """Гейт на текущем состоянии репозитория."""

    def test_repo_has_no_new_violations(self) -> None:
        """Фактический долг зафиксирован в baseline, новых нарушений нет."""
        assert main(["--ci"]) == 0
