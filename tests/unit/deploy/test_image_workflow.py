"""AST-валидация GitHub Actions workflow для container image pipeline.

Sprint 6 Devops: ловит регрессии, при которых ``.github/workflows/image.yml``
отсутствует, потерял jobs (build/scan/sign/push) или переключился с
buildx+cosign+Trivy на другой стек без явного согласования.

Использует ``yaml.safe_load`` (parse tree YAML 1.1) — yaml-парсер строит
token-stream → events → nodes (полноценный AST для YAML); Python-модуль
``ast`` здесь неприменим (YAML ≠ Python). Это согласуется с
``tests/unit/deploy/test_deploy_manifests.py`` для deploy-манифестов и
``tests/unit/frontend/test_arch_ratchet.py`` для arch-проверок.

Проверки:
    * файл существует и парсится как YAML;
    * workflow имеет ``name``, ``on``, ``jobs``, ``concurrency``, ``permissions``;
    * permissions включает ``packages: write`` (push в GHCR);
    * присутствуют 4 job'а: ``build``, ``scan``, ``sign``, ``push``;
    * каждый job имеет ``runs-on`` и непустой ``steps``;
    * build использует ``docker/build-push-action`` и ``docker/setup-buildx-action``;
    * scan использует ``aquasecurity/trivy-action`` с severity HIGH,CRITICAL;
    * sign использует ``sigstore/cosign-installer`` и/или ``cosign sign``;
    * push логинится в ``ghcr.io`` через ``docker/login-action`` и пушит
      через ``docker/build-push-action``;
    * pipeline ordering: scan ждёт build, sign ждёт build+scan, push ждёт sign.
"""
# ruff: noqa: S101  (тесты используют assert)

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest
import yaml

# ── Константы путей и контракта ────────────────────────────────────────

PROJECT_ROOT: Path = Path(__file__).resolve().parents[3]
IMAGE_WORKFLOW: Path = PROJECT_ROOT / ".github" / "workflows" / "image.yml"

REQUIRED_JOBS: frozenset[str] = frozenset({"build", "scan", "sign", "push"})


# ── Helpers ────────────────────────────────────────────────────────────


def _uses_step(job: dict[str, Any], uses_substring: str) -> bool:
    """True если в steps job'а есть ``uses: ...<uses_substring>``.

    Используется для проверки, что job вызывает ожидаемый GitHub Action
    (например, ``aquasecurity/trivy-action``). ``uses`` сравнивается как
    подстрока — допускает любой pin (master / v3 / sha) без хрупкой
    привязки к конкретной версии.
    """
    for step in job.get("steps") or []:
        if not isinstance(step, dict):
            continue
        uses = step.get("uses")
        if isinstance(uses, str) and uses_substring in uses:
            return True
    return False


def _step_with(job: dict[str, Any], action_substring: str) -> list[dict[str, Any]]:
    """Возвращает все step'ы job'а, где ``uses`` содержит подстроку."""
    return [
        step
        for step in (job.get("steps") or [])
        if isinstance(step, dict)
        and isinstance(step.get("uses"), str)
        and action_substring in step["uses"]
    ]


def _needs_set(job: dict[str, Any]) -> set[str]:
    """Нормализует ``needs`` (str | list[str] | None) в set."""
    needs = job.get("needs")
    if needs is None:
        return set()
    if isinstance(needs, str):
        return {needs}
    if isinstance(needs, list):
        return {n for n in needs if isinstance(n, str)}
    return set()


# ── Fixtures ───────────────────────────────────────────────────────────


@pytest.fixture(scope="module")
def workflow() -> dict[str, Any]:
    """Загрузка и парсинг image workflow.

    Module-scope: workflow парсится один раз за тест-сессию (дешёвая
    yaml.safe_load, но экономит повторный disk I/O при parametrize).
    """
    assert IMAGE_WORKFLOW.exists(), (
        f"image workflow missing: {IMAGE_WORKFLOW}. "
        f"Sprint 6 Devops требует .github/workflows/image.yml"
    )
    raw = IMAGE_WORKFLOW.read_text(encoding="utf-8")
    parsed = yaml.safe_load(raw)
    assert isinstance(parsed, dict), (
        f"image.yml должен быть мапом верхнего уровня, "
        f"got {type(parsed).__name__}"
    )
    return parsed


# ── file-level structure ───────────────────────────────────────────────


def test_workflow_top_level_keys(workflow: dict[str, Any]) -> None:
    """Workflow имеет обязательные ключи верхнего уровня."""
    assert "name" in workflow, "image.yml: отсутствует top-level 'name'"
    assert isinstance(workflow["name"], str) and workflow["name"], (
        "image.yml: 'name' должен быть непустой строкой"
    )
    assert "jobs" in workflow, "image.yml: отсутствует top-level 'jobs'"


def test_workflow_has_concurrency(workflow: dict[str, Any]) -> None:
    """Concurrency group обязателен (отмена in-progress на новых push)."""
    assert "concurrency" in workflow, (
        "image.yml должен объявлять concurrency.group для отмены "
        "устаревших runs при повторном push в ту же ветку"
    )
    concurrency = workflow["concurrency"]
    assert isinstance(concurrency, dict), "concurrency должен быть мапом"
    assert "group" in concurrency, "concurrency.group отсутствует"


def test_workflow_has_permissions(workflow: dict[str, Any]) -> None:
    """Permissions включает ``packages: write`` для push в GHCR.

    Без ``packages: write`` GHCR отвергает push с 403 Forbidden; явное
    least-privilege важнее implicit default (write-all), который GitHub
    отключил в 2023 для новых репозиториев.
    """
    perms = workflow.get("permissions") or {}
    assert isinstance(perms, dict), (
        f"permissions должен быть мапом, got {type(perms).__name__}"
    )
    assert perms.get("packages") == "write", (
        "image.yml permissions.packages должен быть 'write' "
        f"(push в ghcr.io требует packages:write), got perms={perms}"
    )


def test_workflow_has_id_token_for_cosign(workflow: dict[str, Any]) -> None:
    """Permissions включает ``id-token: write`` — cosign keyless через OIDC.

    Без этого Fulcio не выдаст signing certificate, cosign sign упадёт
    с ``no IdToken in OIDC request`` error.
    """
    perms = workflow.get("permissions") or {}
    assert perms.get("id-token") == "write", (
        "image.yml permissions.id-token должен быть 'write' "
        "(cosign keyless требует OIDC → Fulcio), "
        f"got perms={perms}"
    )


# ── jobs presence ───────────────────────────────────────────────────────


def test_workflow_jobs_keys(workflow: dict[str, Any]) -> None:
    """Присутствуют все 4 job'а: build, scan, sign, push."""
    jobs = workflow["jobs"]
    assert isinstance(jobs, dict), (
        f"jobs должен быть мапом, got {type(jobs).__name__}"
    )
    actual = set(jobs.keys())
    missing = REQUIRED_JOBS - actual
    assert not missing, (
        f"image.yml jobs отсутствуют: {sorted(missing)}. "
        f"Требуется {sorted(REQUIRED_JOBS)} (Sprint 6 Devops pipeline)"
    )
    extra = actual - REQUIRED_JOBS
    assert not extra, (
        f"image.yml: неожиданные jobs {sorted(extra)} "
        f"(контракт строго {sorted(REQUIRED_JOBS)})"
    )


@pytest.mark.parametrize("job_name", sorted(REQUIRED_JOBS))
def test_job_has_runs_on_and_steps(
    workflow: dict[str, Any], job_name: str
) -> None:
    """Каждый job имеет ``runs-on`` и непустой ``steps``."""
    job = workflow["jobs"][job_name]
    assert isinstance(job, dict), f"job '{job_name}' должен быть мапом"
    assert "runs-on" in job, f"job '{job_name}' без runs-on"
    steps = job.get("steps")
    assert isinstance(steps, list) and steps, (
        f"job '{job_name}' должен иметь непустой steps"
    )


# ── per-job contract ───────────────────────────────────────────────────


def test_build_job_uses_buildx(workflow: dict[str, Any]) -> None:
    """build job использует docker/build-push-action (buildx)."""
    build = workflow["jobs"]["build"]
    assert _uses_step(build, "docker/build-push-action"), (
        "build job должен вызывать docker/build-push-action "
        "(buildx — единственный поддерживаемый builder)"
    )
    assert _uses_step(build, "docker/setup-buildx-action"), (
        "build job должен настроить buildx через docker/setup-buildx-action"
    )


def test_build_job_loads_image_locally(workflow: dict[str, Any]) -> None:
    """build job загружает образ в local daemon (для scan без повторной сборки).

    Проверка ``with.load: true`` в step'ах docker/build-push-action.
    Без load: true downstream-jobs (scan) не получат образ — придётся
    делать повторный build с push, что удваивает время pipeline.
    """
    build = workflow["jobs"]["build"]
    build_steps = _step_with(build, "docker/build-push-action")
    assert build_steps, "build job: нет шагов docker/build-push-action"
    loads = [
        step.get("with", {}).get("load") for step in build_steps
    ]
    assert any(load is True for load in loads), (
        f"build job: docker/build-push-action должен иметь load: true "
        f"(без него scan-jobs не получит локальный образ), got loads={loads}"
    )


def test_scan_job_uses_trivy(workflow: dict[str, Any]) -> None:
    """scan job использует aquasecurity/trivy-action."""
    scan = workflow["jobs"]["scan"]
    assert _uses_step(scan, "aquasecurity/trivy-action"), (
        "scan job должен использовать aquasecurity/trivy-action"
    )


def test_scan_job_severity_blocks_high_critical(workflow: dict[str, Any]) -> None:
    """scan job сканирует на HIGH+CRITICAL — иначе trivy не блокирует push.

    Severity ``HIGH,CRITICAL`` — минимальный блокирующий порог для
    container image pipeline (LOW/MEDIUM — review, не gate).
    """
    scan = workflow["jobs"]["scan"]
    trivy_steps = _step_with(scan, "aquasecurity/trivy-action")
    assert trivy_steps, "scan job: нет шагов aquasecurity/trivy-action"
    severities = [
        step.get("with", {}).get("severity") for step in trivy_steps
    ]
    matched = [
        s for s in severities
        if isinstance(s, str) and "HIGH" in s and "CRITICAL" in s
    ]
    assert matched, (
        "scan job: severity должен включать HIGH и CRITICAL "
        f"(иначе не блокирует push), got severities={severities}"
    )


def test_scan_job_uploads_sarif(workflow: dict[str, Any]) -> None:
    """scan job загружает SARIF в Security tab (видимость для reviewer'ов)."""
    scan = workflow["jobs"]["scan"]
    assert _uses_step(scan, "github/codeql-action/upload-sarif"), (
        "scan job должен загружать trivy SARIF через "
        "github/codeql-action/upload-sarif (видимость в Security tab)"
    )


def test_sign_job_uses_cosign(workflow: dict[str, Any]) -> None:
    """sign job устанавливает cosign и вызывает ``cosign sign``.

    Допустимы оба варианта:
    * ``sigstore/cosign-installer`` + ``cosign sign`` в run-шаге;
    * просто ``cosign sign`` через ``run:`` (если cosign уже в PATH).
    """
    sign = workflow["jobs"]["sign"]
    has_installer = _uses_step(sign, "sigstore/cosign-installer")
    has_cosign_sign = any(
        isinstance(step, dict)
        and isinstance(step.get("run"), str)
        and "cosign sign" in step["run"]
        for step in (sign.get("steps") or [])
    )
    assert has_installer or has_cosign_sign, (
        "sign job должен устанавливать cosign (sigstore/cosign-installer) "
        "или вызывать 'cosign sign' в run-шаге"
    )


def test_push_job_targets_ghcr(workflow: dict[str, Any]) -> None:
    """push job логинится в ghcr.io и пушит через docker/build-push-action.

    Принимает как литерал ``ghcr.io``, так и ссылку на ``env.REGISTRY``
    (DRY через workflow-level env: ``REGISTRY: ghcr.io``) — оба варианта
    корректны для GitHub Actions, парсер yaml.safe_load видит их как
    строки без resolve'а выражений.
    """
    push = workflow["jobs"]["push"]
    assert _uses_step(push, "docker/build-push-action"), (
        "push job должен использовать docker/build-push-action"
    )
    login_steps = _step_with(push, "docker/login-action")
    assert login_steps, (
        "push job должен делать docker/login-action перед push в GHCR"
    )
    registries = [
        step.get("with", {}).get("registry", "") for step in login_steps
    ]
    env_registry = workflow.get("env", {}).get("REGISTRY", "")
    # Разрешаем литерал ``ghcr.io`` или env-ссылку ``${{ env.REGISTRY }}``,
    # которая должна указывать на env.REGISTRY == "ghcr.io" (yaml.safe_load
    # не resolve'ит ${{ ... }}, проверяем оба паттерна на сырых строках).
    matched = [
        r for r in registries
        if "ghcr.io" in r
        or (env_registry == "ghcr.io" and "REGISTRY" in r)
    ]
    assert matched, (
        f"push job login registry должен указывать на ghcr.io "
        f"(литерал или через env.REGISTRY), "
        f"got registries={registries}, env.REGISTRY={env_registry!r}"
    )


# ── pipeline ordering (depends_on) ─────────────────────────────────────


def test_scan_depends_on_build(workflow: dict[str, Any]) -> None:
    """scan ждёт build (нужен image тег/дайджест для trivy image scan)."""
    needs_set = _needs_set(workflow["jobs"]["scan"])
    assert "build" in needs_set, (
        f"scan job должен depends_on: build (нужен image тег), "
        f"got needs={sorted(needs_set)}"
    )


def test_sign_depends_on_build_and_scan(workflow: dict[str, Any]) -> None:
    """sign ждёт build (digest) и scan (блокирующая уязвимость = нет push)."""
    needs_set = _needs_set(workflow["jobs"]["sign"])
    for required in ("build", "scan"):
        assert required in needs_set, (
            f"sign job должен depends_on: {required}, "
            f"got needs={sorted(needs_set)}"
        )


def test_push_depends_on_sign(workflow: dict[str, Any]) -> None:
    """push ждёт sign — не пушим неподписанный image."""
    needs_set = _needs_set(workflow["jobs"]["push"])
    assert "sign" in needs_set, (
        f"push job должен depends_on: sign, got needs={sorted(needs_set)}"
    )
