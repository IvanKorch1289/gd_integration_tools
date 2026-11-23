"""Регресс-тесты на причины красных обязательных workflow (аудит 2026-11-20).

Диагноз выполнен по логам CI-прогонов на HEAD ``bd707471``. Каждый тест
фиксирует одну подтверждённую причину, чтобы дефект нельзя было вернуть
незаметно (правки в workflow — «на глаз», без защиты).

1. **lint.yml / test.yml — ``DatabaseDriverError: драйвер 'psycopg' ...**
   Дефолтный sync-драйвер PostgreSQL — ``psycopg`` (ADR-0363/ADR-0383), он
   объявлен в extra ``sources-cdc``. ``uv sync --locked`` ставит только
   базовые зависимости, поэтому в CI драйвера не было: ``settings.model_dump()``
   (fail-fast DSN-конструктора, ADR-0385 A8) падал → 500 в admin-эндпоинте
   конфигурации и ``failed to collect stats`` в мутационном гейте.
2. **security.yml — «Path does not exist: bandit.sarif».**
   ``bandit`` завершается кодом 1, если находки MEDIUM+ есть (в ``src`` их
   2, HIGH — 0). Шаг исполняется под ``bash -e``, поэтому он падал на первой
   команде: ни SARIF не собирался, ни блокирующий HIGH-гейт не выполнялся.
3. **security.yml — «invalid requirements input: dist/audit-requirements.txt».**
   Файл готовили только ``make sbom`` и ``make audit-deps``, а
   ``make sbom-diff-gate`` (который зовёт ``pip-audit -r``) запускался в CI
   без него → exit 2.
4. **image.yml — «could not parse reference: .».**
   Вход trivy-action называется ``image-ref`` (вход ``image`` удалён из
   action'а), поэтому GitHub отбрасывал его, и trivy получал ``scan-ref``
   по умолчанию — ``.``. Дополнительно ``docker/metadata-action`` не имеет
   выхода ``image``, так что ref образа был пустым, а образ из job'а
   ``build`` недоступен в job'е ``scan`` (другой runner).
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path
from typing import Any, Final

import pytest
import yaml

pytestmark = pytest.mark.unit

PROJECT_ROOT: Final[Path] = Path(__file__).resolve().parents[3]
WORKFLOWS_DIR: Final[Path] = PROJECT_ROOT / ".github" / "workflows"
PYPROJECT: Final[Path] = PROJECT_ROOT / "pyproject.toml"
SECURITY_MK: Final[Path] = PROJECT_ROOT / "make" / "security.mk"

#: Синхронный драйвер PostgreSQL по умолчанию (``database.sync_driver``).
DEFAULT_SYNC_DRIVER: Final[str] = "psycopg"

#: Job'ы, которые гоняют тесты — им нужен установленный DSN-драйвер.
TEST_RUNNING_JOBS: Final[tuple[tuple[str, tuple[str, ...]], ...]] = (
    ("lint.yml", ("lint", "mutation")),
    ("test.yml", ("pytest",)),
)


def _load_workflow(name: str) -> dict[str, Any]:
    """Разобрать workflow-файл.

    Args:
        name: Имя файла в ``.github/workflows``.

    Returns:
        Разобранный mapping.

    """
    data = yaml.safe_load((WORKFLOWS_DIR / name).read_text(encoding="utf-8"))
    assert isinstance(data, dict), f"{name}: ожидался mapping верхнего уровня"
    return data


def _steps(job: dict[str, Any]) -> list[dict[str, Any]]:
    """Все шаги job'а.

    Args:
        job: Разобранный job.

    Returns:
        Список шагов.

    """
    steps = job.get("steps") or []
    return [step for step in steps if isinstance(step, dict)]


def _sync_extras(job: dict[str, Any]) -> set[str]:
    """Extras, установленные ``uv sync`` в шагах job'а.

    Args:
        job: Разобранный job.

    Returns:
        Множество имён extra.

    """
    extras: set[str] = set()
    for step in _steps(job):
        run = str(step.get("run", ""))
        for line in run.splitlines():
            if "uv sync" not in line:
                continue
            extras.update(re.findall(r"--extra[= ]+([A-Za-z0-9_.-]+)", line))
    return extras


def _optional_dependencies() -> dict[str, list[str]]:
    """Содержимое ``[project.optional-dependencies]``.

    Returns:
        Мап extra → список требований.

    """
    data = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))
    dependencies = data.get("project", {}).get("optional-dependencies", {})
    return {str(name): list(reqs) for name, reqs in dependencies.items()}


def _extra_provides(extra: str, distribution: str) -> bool:
    """Объявляет ли extra указанный дистрибутив.

    Args:
        extra: Имя extra из ``[project.optional-dependencies]``.
        distribution: Имя дистрибутива (например ``psycopg``).

    Returns:
        ``True``, если extra содержит требование с таким именем.

    """
    for requirement in _optional_dependencies().get(extra, []):
        name = re.split(r"[<>=!~;\[\s]", requirement, maxsplit=1)[0].strip().lower()
        if name == distribution.lower():
            return True
    return False


def _make_target(text: str, target: str) -> tuple[str, str]:
    """Разобрать make-цель: строку заголовка и тело рецепта.

    Args:
        text: Содержимое make-файла.
        target: Имя цели.

    Returns:
        Пара ``(заголовок цели, тело рецепта)``.

    """
    lines = text.splitlines()
    start = next(i for i, line in enumerate(lines) if line.startswith(f"{target}:"))
    body: list[str] = []
    for line in lines[start + 1 :]:
        if line and not line[0].isspace() and not line.startswith(("##", "#")):
            break
        body.append(line)
    return lines[start], "\n".join(body)


class TestCiInstallsDefaultSyncDriver:
    """CI обязан ставить extra дефолтного sync-драйвера PostgreSQL."""

    @pytest.mark.parametrize(("workflow_name", "job_names"), TEST_RUNNING_JOBS)
    def test_test_running_jobs_install_sync_driver(
        self, workflow_name: str, job_names: tuple[str, ...]
    ) -> None:
        """Job'ы, гоняющие тесты, ставят extra с ``psycopg``.

        Без драйвера ``settings.model_dump()`` (admin-конфиг, ADR-0385 A8)
        и ``test_connection_safety.py`` падают с ``DatabaseDriverError``.
        """
        workflow = _load_workflow(workflow_name)
        for job_name in job_names:
            job = workflow["jobs"][job_name]
            extras = _sync_extras(job)
            assert any(
                _extra_provides(extra, DEFAULT_SYNC_DRIVER) for extra in extras
            ), (
                f"{workflow_name}:{job_name}: ни один --extra не даёт "
                f"'{DEFAULT_SYNC_DRIVER}' (sync-драйвер PostgreSQL) — "
                f"settings.model_dump() упадёт с DatabaseDriverError; "
                f"extras={sorted(extras)}"
            )

    def test_sync_keeps_lock_file_untouched(self) -> None:
        """``uv sync`` остаётся ``--locked`` — lock-файлы не переписываются."""
        for workflow_name, job_names in TEST_RUNNING_JOBS:
            workflow = _load_workflow(workflow_name)
            for job_name in job_names:
                for step in _steps(workflow["jobs"][job_name]):
                    run = str(step.get("run", ""))
                    if "uv sync" not in run:
                        continue
                    assert "--locked" in run or "--frozen" in run, (
                        f"{workflow_name}:{job_name}: uv sync без --locked/--frozen"
                    )


class TestSecurityBanditStep:
    """Бандит-шаг security.yml обязан дойти до SARIF и до HIGH-гейта."""

    def test_sarif_built_even_when_bandit_reports_findings(self) -> None:
        """Отчёт bandit не обрывает шаг до конвертации SARIF.

        ``bandit`` завершается кодом 1 при находках MEDIUM+; под ``bash -e``
        это роняло шаг на первой команде — SARIF не появлялся, а upload
        падал с «Path does not exist: bandit.sarif».
        """
        workflow = _load_workflow("security.yml")
        step = next(
            step
            for step in _steps(workflow["jobs"]["bandit"])
            if "bandit" in str(step.get("run", ""))
        )
        run = str(step.get("run", ""))

        assert "bandit_json_to_sarif.py" in run, "шаг должен собирать SARIF"
        report_lines = [line for line in run.splitlines() if "-f json" in line]
        assert report_lines, "шаг должен формировать JSON-отчёт bandit"
        for line in report_lines:
            assert "||" in line, (
                "bandit возвращает код 1 при находках MEDIUM+ — команда "
                "формирования отчёта должна это переживать, иначе шаг падает "
                "до конвертации SARIF"
            )

    def test_high_severity_gate_stays_blocking(self) -> None:
        """Блокирующий HIGH-гейт остаётся в том же шаге."""
        workflow = _load_workflow("security.yml")
        step = next(
            step
            for step in _steps(workflow["jobs"]["bandit"])
            if "bandit" in str(step.get("run", ""))
        )

        assert "--severity-level high" in str(step.get("run", "")), (
            "блокирующий HIGH-гейт bandit должен остаться в шаге"
        )


class TestSbomDiffGatePreparesRequirements:
    """``make sbom-diff-gate`` обязан сам подготовить requirements для pip-audit."""

    def test_target_depends_on_requirements_preparation(self) -> None:
        """Цель ``sbom-diff-gate`` зависит от ``audit-requirements``."""
        text = SECURITY_MK.read_text(encoding="utf-8")
        header, _ = _make_target(text, "sbom-diff-gate")

        assert "audit-requirements" in header, (
            "make sbom-diff-gate должен зависеть от audit-requirements: иначе "
            "pip-audit получает несуществующий dist/audit-requirements.txt "
            "(invalid requirements input → exit 2)"
        )

    def test_requirements_target_writes_audit_file(self) -> None:
        """``audit-requirements`` готовит runtime-only файл с пинами."""
        text = SECURITY_MK.read_text(encoding="utf-8")
        _, body = _make_target(text, "audit-requirements")

        assert "dist/audit-requirements.txt" in body
        assert re.search(r"uv\s+export\s+--no-dev\s+--no-all-extras", body), (
            "requirements для pip-audit собираются из runtime-only export "
            "(optional extras исключены)"
        )

    def test_gate_uses_prepared_requirements(self) -> None:
        """pip-audit в гейте читает тот же файл, что готовит audit-requirements."""
        text = SECURITY_MK.read_text(encoding="utf-8")
        _, body = _make_target(text, "sbom-diff-gate")

        assert "-r dist/audit-requirements.txt" in body

    def test_gate_requires_fresh_audit_report(self) -> None:
        """Гейт требует свежий отчёт, но не падает на коде pip-audit «1 = CVE».

        Вердикт по CVE в этом гейте выносит ``sbom_diff_gate.py`` (новые ID
        против baseline минус allowlist), а код 1 самого pip-audit означает
        лишь «найдены уязвимости». Провал сканера ловится удалением старого
        отчёта и проверкой непустого свежего файла.
        """
        text = SECURITY_MK.read_text(encoding="utf-8")
        _, body = _make_target(text, "sbom-diff-gate")

        assert re.search(r"rm\s+-f\s+dist/pip-audit\.json", body), (
            "старый отчёт pip-audit должен удаляться перед сканом"
        )
        assert re.search(r"test\s+-s\s+dist/pip-audit\.json", body), (
            "после скана обязана проверяться непустота свежего отчёта"
        )
        audit_lines = [
            line
            for line in body.splitlines()
            if "pip-audit --" in line and not line.strip().startswith("#")
        ]
        assert audit_lines
        assert all("|| true" in line for line in audit_lines), (
            "код возврата pip-audit (1 = найдены CVE) не является вердиктом "
            "этого гейта — вердикт выносит sbom_diff_gate.py"
        )


class TestImageWorkflowTrivy:
    """image.yml: trivy получает существующий вход и реальный ref образа."""

    def test_trivy_uses_image_ref_input(self) -> None:
        """Вход trivy-action — ``image-ref`` (вход ``image`` удалён)."""
        workflow = _load_workflow("image.yml")
        trivy_steps = [
            step
            for job in workflow["jobs"].values()
            for step in _steps(job)
            if "trivy-action" in str(step.get("uses", ""))
        ]
        assert trivy_steps, "image.yml: не найдено ни одного шага trivy-action"

        for step in trivy_steps:
            inputs = step.get("with") or {}
            assert "image" not in inputs, (
                "у trivy-action нет входа 'image' — GitHub отбрасывает его, "
                "и trivy сканирует scan-ref по умолчанию ('.')"
            )
            if inputs.get("scan-type") == "image":
                assert inputs.get("image-ref"), (
                    "сканирование образа требует непустого image-ref"
                )

    def test_metadata_action_image_output_not_used(self) -> None:
        """``docker/metadata-action`` не имеет выхода ``image``.

        Обращение к нему давало пустой ref: образ собирался без тега, а
        trivy/cosign получали пустую ссылку.
        """
        text = (WORKFLOWS_DIR / "image.yml").read_text(encoding="utf-8")
        code = "\n".join(
            line for line in text.splitlines() if not line.strip().startswith("#")
        )

        assert "steps.meta.outputs.image" not in code, (
            "у docker/metadata-action нет выхода 'image' (есть tags/version/"
            "digest/labels/annotations/json) — ref всегда был пустым"
        )

    def test_build_job_exports_image_ref(self) -> None:
        """Job ``build`` экспортирует непустой ref образа."""
        workflow = _load_workflow("image.yml")
        outputs = workflow["jobs"]["build"].get("outputs") or {}

        assert outputs.get("image"), "build job не экспортирует image ref"

    def test_scan_job_has_image_available(self) -> None:
        """В job'е ``scan`` образ доступен локально.

        Образ из job'а ``build`` остаётся в его локальном docker-демоне
        (другой runner), а пушить до сканирования нельзя — scan блокирует
        push. Значит образ нужно собрать (с ``load: true``) или загрузить
        в job'е ``scan``.
        """
        workflow = _load_workflow("image.yml")
        steps = _steps(workflow["jobs"]["scan"])

        builds_locally = any(
            "docker/build-push-action" in str(step.get("uses", ""))
            and (step.get("with") or {}).get("load") is True
            for step in steps
        )
        loads_tar = any("docker load" in str(step.get("run", "")) for step in steps)

        assert builds_locally or loads_tar, (
            "job scan не делает образ доступным trivy: образ из job build "
            "на этом runner отсутствует"
        )
