"""Регресс-тесты meta-гейта ``check_release_gate.py`` (аудит 2026-10-01, F-Z).

F-Z доказано эмпирически: ``.github/workflows/release-gate.yml`` завершался с
exit 1 при **любом** SHA из-за двух независимых дефектов.

* F-Z.1 — ``REPO`` использовалась в ``gh api`` под ``set -u``, но не была
  объявлена: bash падал «unbound variable» до самой агрегации результатов;
* F-Z.2 — в ``REQUIRED`` стоял ``build-and-deploy`` (имя job'а из
  ``docs-publish.yml``) вместо ``image.yml``: ``workflow_runs`` всегда пуст →
  ``conclusion: missing`` → гейт всегда FAIL даже после фикса F-Z.1.

Эти тесты закрывают оба класса на уровне исходников репозитория, а не
на уровне GitHub Actions: ни один существующий гейт их не ловил.

Согласуется с ``tests/unit/deploy/test_image_workflow.py`` (AST/YAML-проверки
GitHub Actions workflow) и ``tests/unit/frontend/test_arch_ratchet.py``.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest
import yaml

PROJECT_ROOT: Path = Path(__file__).resolve().parents[3]
GATE_PATH: Path = PROJECT_ROOT / ".github" / "workflows" / "release-gate.yml"
WORKFLOWS_DIR: Path = PROJECT_ROOT / ".github" / "workflows"
CHECKER_PATH: Path = PROJECT_ROOT / "tools" / "checks" / "check_release_gate.py"


def _load_checker() -> ModuleType:
    """Загрузить ``check_release_gate.py`` как модуль (tools/ не пакет).

    Returns:
        Модуль с ``check_gate`` / ``main`` / ``_script_uses_nounset``.
    """
    spec = importlib.util.spec_from_file_location("check_release_gate", CHECKER_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def checker() -> ModuleType:
    """Модуль гейта, загруженный один раз на модуль.

    Returns:
        Загруженный модуль ``check_release_gate``.
    """
    return _load_checker()


@pytest.fixture(scope="module")
def gate_doc() -> dict[str, Any]:
    """Разобранный ``release-gate.yml``.

    Returns:
        YAML-маппинг workflow.
    """
    return yaml.safe_load(GATE_PATH.read_text(encoding="utf-8"))


def _required(gate_text: str) -> list[str]:
    """Извлечь список ``REQUIRED`` из текста скрипта.

    Args:
        gate_text: Содержимое ``release-gate.yml``.

    Returns:
        Список идентификаторов workflow.
    """
    block = gate_text.split("REQUIRED=(", 1)[1].split(")", 1)[0]
    return [line.strip().strip('"') for line in block.splitlines() if line.strip()]


# ── F-Z.1: переменная REPO обязана быть объявлена ──────────────────────


def test_repo_env_declared(gate_doc: dict[str, Any]) -> None:
    """F-Z.1 не должен вернуться: ``REPO`` объявлена в ``env:`` шага.

    Args:
        gate_doc: Разобранный ``release-gate.yml``.
    """
    step = gate_doc["jobs"]["aggregate"]["steps"][-1]
    assert step["env"]["REPO"] == "${{ github.repository }}", (
        "F-Z.1: без REPO в env скрипт падает 'unbound variable' под set -u"
    )


def test_gate_script_uses_nounset(checker: ModuleType) -> None:
    """Скрипт гейта действительно работает под ``set -u`` (иначе проверка фиктивна).

    Args:
        checker: Модуль гейта.
    """
    text = GATE_PATH.read_text(encoding="utf-8")
    assert checker._script_uses_nounset(text), (
        "ожидается 'set -euo pipefail' в release-gate.yml"
    )


@pytest.mark.parametrize(
    ("script", "expected"),
    [
        ("set -euo pipefail\necho hi", True),
        ("set -u\necho hi", True),
        ("set -eu\necho hi", True),
        ("set -o errexit -o nounset\necho hi", True),
        ("set -o nounset\necho hi", True),
        ("set -o errexit\nset --nounset\necho hi", True),
        ("set -eo pipefail\necho hi", False),
        ("echo hi", False),
    ],
)
def test_nounset_parsing(checker: ModuleType, script: str, expected: bool) -> None:
    """Кластер коротких опций ``-euo`` разбирается посимвольно.

    Args:
        checker: Модуль гейта.
        script: Текст shell-скрипта.
        expected: Ожидаемый результат разбора.
    """
    assert checker._script_uses_nounset(script) is expected


# ── F-Z.2: REQUIRED разрешается в реальные workflow-файлы ───────────────


def test_required_are_existing_workflow_files() -> None:
    """Каждый ``REQUIRED`` — существующий файл с триггером ``pull_request``."""
    for workflow_id in _required(GATE_PATH.read_text(encoding="utf-8")):
        assert workflow_id.endswith((".yml", ".yaml")), (
            f"REQUIRED[{workflow_id}]: GitHub API принимает ID или имя файла, "
            f"а не имя job'а / значение 'name:'"
        )
        path = WORKFLOWS_DIR / workflow_id
        assert path.is_file(), f"REQUIRED[{workflow_id}]: workflow-файла не существует"
        doc = yaml.safe_load(path.read_text(encoding="utf-8"))
        triggers = doc.get("on", doc.get(True))
        assert isinstance(triggers, (list, dict)) and "pull_request" in triggers, (
            f"REQUIRED[{workflow_id}]: без pull_request для SHA из PR не будет run'а"
        )


def test_build_and_deploy_is_not_a_workflow() -> None:
    """F-Z.2 не должен вернуться: контейнерный pipeline — это ``image.yml``."""
    assert "build-and-deploy" not in _required(GATE_PATH.read_text(encoding="utf-8"))
    assert (WORKFLOWS_DIR / "image.yml").is_file()
    assert not (WORKFLOWS_DIR / "build-and-deploy.yml").exists()


# ── Поведение гейта на текущем репозитории ─────────────────────────────


def test_gate_reports_no_violations(checker: ModuleType) -> None:
    """На неизменённом репозитории гейт не находит нарушений.

    Args:
        checker: Модуль гейта.
    """
    assert checker.check_gate(GATE_PATH, WORKFLOWS_DIR) == []


def test_gate_exit_codes(checker: ModuleType) -> None:
    """0 — чисто; 1 — нарушения; 2 — инструментальная ошибка (не PASS).

    Args:
        checker: Модуль гейта.
    """
    assert (
        checker.main(["--gate", str(GATE_PATH), "--workflows-dir", str(WORKFLOWS_DIR)])
        == 0
    )
    assert checker.main(["--gate", str(WORKFLOWS_DIR / "no-such-gate.yml")]) == 2


# ── Мутационные сценарии: гейт обязан ловить регрессии ─────────────────


def _stage(tmp_path: Path, gate_text: str) -> Path:
    """Разложить workflow-файлы и гейт по временному каталогу.

    Args:
        tmp_path: Временный каталог pytest.
        gate_text: Текст ``release-gate.yml``.

    Returns:
        Путь к staged-гейту.
    """
    workflows = tmp_path / "workflows"
    workflows.mkdir()
    for source in WORKFLOWS_DIR.glob("*.yml"):
        (workflows / source.name).write_text(
            source.read_text(encoding="utf-8"), encoding="utf-8"
        )
    gate = workflows / "release-gate.yml"
    gate.write_text(gate_text, encoding="utf-8")
    return gate


def test_detects_unbound_variable(checker: ModuleType, tmp_path: Path) -> None:
    """Удаление ``REPO`` из ``env:`` должно дать нарушение (F-Z.1).

    Args:
        checker: Модуль гейта.
        tmp_path: Временный каталог pytest.
    """
    text = GATE_PATH.read_text(encoding="utf-8").replace(
        "          REPO: ${{ github.repository }}\n", ""
    )
    gate = _stage(tmp_path, text)
    violations = checker.check_gate(gate, gate.parent)
    assert any("REPO" in v and "unbound variable" in v for v in violations), violations


def test_detects_missing_workflow_file(checker: ModuleType, tmp_path: Path) -> None:
    """Ссылка на несуществующий workflow-файл должна дать нарушение (F-Z.2).

    Args:
        checker: Модуль гейта.
        tmp_path: Временный каталог pytest.
    """
    text = GATE_PATH.read_text(encoding="utf-8").replace(
        '"image.yml"', '"image-gone.yml"'
    )
    gate = _stage(tmp_path, text)
    violations = checker.check_gate(gate, gate.parent)
    assert any("image-gone.yml" in v and "workflow_runs" in v for v in violations), (
        violations
    )


def test_detects_workflow_without_pull_request(
    checker: ModuleType, tmp_path: Path
) -> None:
    """Требование без ``pull_request`` должно дать нарушение.

    Args:
        checker: Модуль гейта.
        tmp_path: Временный каталог pytest.
    """
    gate = _stage(tmp_path, GATE_PATH.read_text(encoding="utf-8"))
    upstream = gate.parent / "stubs-drift.yml"
    upstream.write_text(
        upstream.read_text(encoding="utf-8").replace("  pull_request:\n", "", 1),
        encoding="utf-8",
    )
    violations = checker.check_gate(gate, gate.parent)
    assert any("stubs-drift.yml" in v and "pull_request" in v for v in violations), (
        violations
    )


def test_original_head_gate_is_rejected(checker: ModuleType, tmp_path: Path) -> None:
    """Версия гейта до F-Z обязана отвергаться гейтом — базовая линия регрессии.

    Args:
        checker: Модуль гейта.
        tmp_path: Временный каталог pytest.
    """
    legacy = """\
jobs:
  aggregate:
    steps:
      - env:
          GH_TOKEN: ${{ secrets.GITHUB_TOKEN }}
        run: |
          set -euo pipefail
          REQUIRED=(
            "lint"
            "build-and-deploy"
          )
          for WORKFLOW in "${REQUIRED[@]}"; do
            gh api "/repos/${REPO}/actions/runs?head_sha=${SHA}" > /dev/null
          done
"""
    gate = _stage(tmp_path, legacy)
    violations = checker.check_gate(gate, gate.parent)
    assert any("build-and-deploy" in v for v in violations), violations
    assert any("REPO" in v for v in violations), violations
