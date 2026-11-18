"""Регрессия: целостность CI-workflow (аудит 2026-11-18).

Зона: ``.github/workflows/**`` + ``pyproject.toml`` (состав extras).
Проверки статические — GitHub Actions не запускаются.

Подтверждённые дефекты, закрытые этим файлом:

1. **Несуществующий extra.** ``api-fuzz.yml`` выполнял ``uv sync --extra dev``,
   но ``dev`` — это *dependency-group*, а не extra из
   ``[project.optional-dependencies]``. ``uv sync`` падал с
   ``Extra `dev` is not defined in the project's `optional-dependencies` table``,
   а job при этом оставался «зелёным» из-за ``continue-on-error: true`` —
   фаззинг не запускался НИКОГДА, и это нигде не было видно.
2. **Воспроизводимость.** ``uv sync`` без ``--locked``/``--frozen`` может
   перерезолвить lock-файл прямо в CI → в раннере ставится не тот набор
   пакетов, что в lock (в т.ч. потенциально уязвимая версия).
3. **Отсутствующий ``permissions``.** ``ai-pr-review.yml`` и
   ``release-gate.yml`` не объявляли блок прав → workflow наследовал
   дефолтные права токена репозитория (часто read/write). При этом
   ``release-gate`` читает статусы прогонов через
   ``gh api /repos/{repo}/actions/runs`` — нужен ``actions: read``.
4. **Подвижная ветка вместо релиза.** ``aquasecurity/trivy-action@master``
   — содержимое action'а менялось без review и без auditable-версии.
5. **Фейковые «гейты».** В ``ai-pr-review.yml`` шаги «AI Layer Policy /
   AI Security / AI Performance Regression Check» были заглушками
   ``python -c "print('...: PASS')"`` — они ВСЕГДА печатали PASS, ничего
   не проверяя, и в логе CI выглядели как пройденные гейты.
6. **Мутационный гейт, который никогда не измерял.** Шаг
   «Mutation score gate» жил внутри job'а ``lint`` с общим таймаутом
   15 минут и 4-минутным бюджетом гейта, тогда как полный прогон
   мутаций занимает часы → гейт ВСЕГДА возвращал SKIPPED (exit 2).
   Теперь это отдельный job ``mutation`` с кэшем ``mutants/``.
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
LINT_WORKFLOW: Final[Path] = WORKFLOWS_DIR / "lint.yml"

#: Экшены, которые нельзя тянуть с подвижной ветки — только релизный тег.
FORBIDDEN_ACTION_REFS: Final[frozenset[str]] = frozenset({"master", "main", "HEAD"})


def _workflow_files() -> list[Path]:
    """Все workflow-файлы репозитория."""
    return sorted(WORKFLOWS_DIR.glob("*.yml"))


def _load_workflow(path: Path) -> dict[str, Any]:
    """Разобрать workflow.

    Args:
        path: Путь к workflow-файлу.

    Returns:
        Разобранный mapping.

    """
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    assert isinstance(data, dict)
    return data


def _iter_steps(workflow: dict[str, Any]) -> list[tuple[str, str, dict[str, Any]]]:
    """Все шаги всех job'ов workflow.

    Args:
        workflow: Разобранный workflow.

    Returns:
        Список кортежей ``(job, step-name, step)``.

    """
    result: list[tuple[str, str, dict[str, Any]]] = []
    for job_name, job in (workflow.get("jobs") or {}).items():
        for step in job.get("steps") or []:
            result.append((job_name, str(step.get("name", "")), step))
    return result


def _declared_extras() -> set[str]:
    """Объявленные extras из ``[project.optional-dependencies]``."""
    data = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))
    return set(data.get("project", {}).get("optional-dependencies", {}))


def _declared_groups() -> set[str]:
    """Объявленные dependency-groups."""
    data = tomllib.loads(PYPROJECT.read_text(encoding="utf-8"))
    return set(data.get("dependency-groups", {}))


class TestUvSyncInvocations:
    """``uv sync`` в CI обязан быть воспроизводимым и валидным."""

    def test_all_syncs_use_locked_or_frozen(self) -> None:
        """Каждый ``uv sync`` использует ``--locked`` или ``--frozen``.

        Регресс: ``uv sync`` без флага может перерезолвить lock прямо в CI.
        """
        offenders: list[str] = []
        for path in _workflow_files():
            for line in path.read_text(encoding="utf-8").splitlines():
                stripped = line.strip()
                if not stripped.startswith("run:") or "uv sync" not in stripped:
                    continue
                if "--locked" not in stripped and "--frozen" not in stripped:
                    offenders.append(f"{path.name}: {stripped}")

        assert not offenders, "uv sync без --locked/--frozen:\n" + "\n".join(offenders)

    def test_sync_extras_are_declared(self) -> None:
        """Каждый ``--extra X`` ссылается на существующий extra.

        Регресс: ``--extra dev`` в api-fuzz.yml — такого extra нет, шап
        падал, а job оставался зелёным.
        """
        extras = _declared_extras()
        groups = _declared_groups()
        offenders: list[str] = []
        for path in _workflow_files():
            for line in path.read_text(encoding="utf-8").splitlines():
                stripped = line.strip()
                if "uv sync" not in stripped or not stripped.startswith("run:"):
                    continue
                for extra in re.findall(r"--extra\s+([A-Za-z0-9_.-]+)", stripped):
                    if extra not in extras and extra not in groups:
                        offenders.append(
                            f"{path.name}: --extra {extra} (нет ни extra, ни группы)"
                        )

        assert not offenders, "несуществующие extras:\n" + "\n".join(offenders)


class TestWorkflowPermissions:
    """Каждый workflow объявляет минимальные права токена."""

    def test_every_workflow_has_permissions_block(self) -> None:
        """Блок ``permissions`` объявлен явно в каждом workflow.

        Регресс: ``ai-pr-review.yml`` и ``release-gate.yml`` наследовали
        дефолтные права токена репозитория.
        """
        missing = [
            path.name
            for path in _workflow_files()
            if "permissions" not in _load_workflow(path)
        ]

        assert not missing, f"workflow без блока permissions: {missing}"

    def test_release_gate_can_read_workflow_runs(self) -> None:
        """``release-gate.yml`` имеет ``actions: read``.

        Гейт читает статусы прогонов через
        ``gh api /repos/{repo}/actions/runs`` — без ``actions: read``
        GitHub срезает права до none и запрос падает с 403.
        """
        perms = _load_workflow(WORKFLOWS_DIR / "release-gate.yml")["permissions"]

        assert perms.get("actions") == "read", perms
        assert perms.get("contents") == "read", perms

    def test_ai_pr_review_can_write_comments_only_where_needed(self) -> None:
        """``ai-pr-review.yml`` — read кода + write комментария в PR."""
        perms = _load_workflow(WORKFLOWS_DIR / "ai-pr-review.yml")["permissions"]

        assert perms.get("contents") == "read", perms
        assert perms.get("pull-requests") == "write", perms


class TestActionPinning:
    """Action'ы не тянутся с подвижных веток."""

    def test_no_action_refs_from_moving_branches(self) -> None:
        """Ни один action не берётся с ``master``/``main``/``HEAD``.

        Регресс: ``aquasecurity/trivy-action@master`` — содержимое action'а
        менялось без review и без auditable-версии.
        """
        offenders: list[str] = []
        for path in _workflow_files():
            for line in path.read_text(encoding="utf-8").splitlines():
                match = re.search(r"uses:\s*([^\s#]+)@([^\s#]+)", line)
                if not match:
                    continue
                if match.group(2) in FORBIDDEN_ACTION_REFS:
                    offenders.append(f"{path.name}: {line.strip()}")

        assert not offenders, "action с подвижной ветки:\n" + "\n".join(offenders)

    def test_trivy_action_pinned_to_release(self) -> None:
        """``trivy-action`` закреплён на релизном теге."""
        for path in (WORKFLOWS_DIR / "security.yml", WORKFLOWS_DIR / "image.yml"):
            text = path.read_text(encoding="utf-8")
            match = re.search(r"aquasecurity/trivy-action@([^\s#]+)", text)
            assert match, f"{path.name}: trivy-action не найден"
            assert re.fullmatch(r"v\d+\.\d+\.\d+", match.group(1)), (
                f"{path.name}: trivy-action@{match.group(1)} — не релизный тег"
            )


class TestNoFakeGates:
    """CI-шаг не должен имитировать проверку."""

    def test_no_always_pass_print_steps(self) -> None:
        """Нет шагов вида ``python -c "print('...: PASS')"``.

        Регресс: три «AI-гейта» в ai-pr-review.yml всегда печатали PASS,
        ничего не проверяя, и выглядели в логе CI как пройденные проверки.
        """
        offenders: list[str] = []
        pattern = re.compile(r"print\(\s*['\"][^'\"]*PASS", re.IGNORECASE)
        for path in _workflow_files():
            for job, name, step in _iter_steps(_load_workflow(path)):
                run = str(step.get("run", ""))
                if pattern.search(run):
                    offenders.append(f"{path.name}:{job}:{name}")

        assert not offenders, f"шаги-заглушки, всегда печатающие PASS: {offenders}"


class TestMutationGateIsReal:
    """Мутационный гейт должен быть измеримым, а не декоративным."""

    def test_mutation_gate_is_separate_job(self) -> None:
        """Мутационный гейт — отдельный job, а не шаг внутри ``lint``.

        Регресс: внутри job'а ``lint`` (таймаут 15 мин) гейт с бюджетом
        4 минут при полном прогоне в часы ВСЕГДА возвращал SKIPPED.
        """
        workflow = _load_workflow(LINT_WORKFLOW)
        jobs = workflow.get("jobs") or {}

        assert "mutation" in jobs, "в lint.yml нет отдельного job'а mutation"
        assert workflow["jobs"]["mutation"].get("timeout-minutes", 0) >= 30, (
            "job mutation: таймаут меньше 30 минут — полный прогон не успеет"
        )

        lint_steps = {
            name
            for job, name, _ in _iter_steps({"jobs": {"lint": jobs["lint"]}})
            if job == "lint"
        }
        assert not any("mutation" in name.lower() for name in lint_steps), (
            "мутационный гейт всё ещё является шагом внутри job'а lint"
        )

    def test_mutation_job_caches_mutants_workspace(self) -> None:
        """Job ``mutation`` кэширует рабочую копию ``mutants/``.

        Без кэша каждый прогон стартует с нуля (часы), и гейт не может
        завершиться в бюджет — то есть остаётся SKIPPED.
        """
        workflow = _load_workflow(LINT_WORKFLOW)
        steps = workflow["jobs"]["mutation"]["steps"]
        cache_steps = [
            step
            for step in steps
            if str(step.get("uses", "")).startswith("actions/cache")
            and "mutants" in str((step.get("with") or {}).get("path", ""))
        ]

        assert cache_steps, "job mutation не кэширует mutants/"
        assert (cache_steps[0]["with"] or {}).get("restore-keys"), (
            "нет restore-keys — PR не восстановит кэш базовой ветки"
        )

    def test_mutation_gate_budget_exceeds_former_budget(self) -> None:
        """Бюджет гейта в job'е ``mutation`` больше прежних 240 секунд."""
        workflow = _load_workflow(LINT_WORKFLOW)
        steps = workflow["jobs"]["mutation"]["steps"]
        gate = next(
            step for step in steps if "check_mutmut.py" in str(step.get("run", ""))
        )
        env = gate.get("env") or {}

        assert int(env.get("MUTATION_GATE_TIMEOUT", "0")) > 240, env
