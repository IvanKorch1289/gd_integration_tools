"""AST-валидация GitHub Actions workflow для container image pipeline.

Sprint 6 Devops + аудит 2026-11-23 (ЭТАП 1): ловит регрессии, при которых
``.github/workflows/image.yml`` потерял jobs, разорвал порядок
«build → push по digest → scan → sign → verify → promote» или вернул
не-якорный identity-регексп подписи.

Использует ``yaml.safe_load`` (parse tree YAML 1.1) — yaml-парсер строит
token-stream → events → nodes (полноценный AST для YAML); Python-модуль
``ast`` здесь неприменим (YAML ≠ Python). Это согласуется с
``tests/unit/deploy/test_deploy_manifests.py`` для deploy-манифестов и
``tests/unit/frontend/test_arch_ratchet.py`` для arch-проверок.

Проверки:
    * файл существует и парсится как YAML;
    * workflow имеет ``name``, ``on``, ``jobs``, ``concurrency``, ``permissions``;
    * permissions включает ``packages: write`` (push в GHCR) и ``id-token: write``;
    * присутствуют 7 job'ов: ревью-ветка (build, scan) и ветка публикации
      (build_release, scan_release, sign, verify, promote);
    * ревью-ветка не публикует: ``load: true`` и ``push: false``;
    * публикация идёт ПО DIGEST (``push-by-digest=true``) — пользовательских
      тегов в registry до проверки подписи не появляется;
    * сканируется, подписывается и публикуется ОДИН И ТОТ ЖЕ digest;
    * verify сверяет identity по ЯКОРНОМУ regex: чужой репозиторий/workflow/
      ref не проходит (регексп проверяется офлайн — реальный сертификат
      cosign в офлайн-окружении недоступен, см. отчёт аудита: ENV_BLOCKED);
    * ветка публикации запускается только на ``push`` — ни pull_request, ни
      merge_group не подписывают и не публикуют.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import pytest
import yaml

# ── Константы путей и контракта ────────────────────────────────────────

PROJECT_ROOT: Path = Path(__file__).resolve().parents[3]
IMAGE_WORKFLOW: Path = PROJECT_ROOT / ".github" / "workflows" / "image.yml"

#: Ветка ревью: сборка локального образа + скан, без публикации.
REVIEW_JOBS: frozenset[str] = frozenset({"build", "scan"})

#: Ветка публикации: push по digest → скан → подпись → проверка → теги.
RELEASE_JOBS: frozenset[str] = frozenset(
    {"build_release", "scan_release", "sign", "verify", "promote"}
)

REQUIRED_JOBS: frozenset[str] = REVIEW_JOBS | RELEASE_JOBS

#: Subject сертификата cosign (keyless, GitHub OIDC) — ожидаемая форма.
EXPECTED_SUBJECT: str = (
    "https://github.com/IvanKorch1289/gd_integration_tools/"
    ".github/workflows/image.yml@refs/heads/master"
)


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


def _run_steps(job: dict[str, Any]) -> list[str]:
    """Тексты всех ``run:``-шагов job'а."""
    return [
        step["run"]
        for step in (job.get("steps") or [])
        if isinstance(step, dict) and isinstance(step.get("run"), str)
    ]


def _job_text(job: dict[str, Any]) -> str:
    """Всё текстовое содержимое job'а: run-шаги + значения env.

    Digest передаётся в шаг через ``env:`` (``DIGEST: ${{ ... }}``), поэтому
    проверка «job оперирует digest'ом из build_release» должна смотреть и
    в env (job-level и step-level), а не только в текст run-шага.
    """
    chunks: list[str] = list(_run_steps(job))
    envs = [job.get("env") or {}]
    for step in job.get("steps") or []:
        if isinstance(step, dict):
            envs.append(step.get("env") or {})
    for env in envs:
        if isinstance(env, dict):
            chunks.extend(str(value) for value in env.values())
    return " ".join(chunks)


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


def _job_if(job: dict[str, Any]) -> str:
    """Условие запуска job'а строкой (пустая строка — без условия)."""
    value = job.get("if")
    return value if isinstance(value, str) else ""


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
        f"image.yml должен быть мапом верхнего уровня, got {type(parsed).__name__}"
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
    """Присутствуют все job'ы обеих веток pipeline."""
    jobs = workflow["jobs"]
    assert isinstance(jobs, dict), f"jobs должен быть мапом, got {type(jobs).__name__}"
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
def test_job_has_runs_on_and_steps(workflow: dict[str, Any], job_name: str) -> None:
    """Каждый job имеет ``runs-on`` и непустой ``steps``."""
    job = workflow["jobs"][job_name]
    assert isinstance(job, dict), f"job '{job_name}' должен быть мапом"
    assert "runs-on" in job, f"job '{job_name}' без runs-on"
    steps = job.get("steps")
    assert isinstance(steps, list) and steps, (
        f"job '{job_name}' должен иметь непустой steps"
    )


# ── ревью-ветка: build + scan, без публикации ──────────────────────────


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


def test_review_build_loads_locally_without_push(workflow: dict[str, Any]) -> None:
    """Ревью-сборка загружается в локальный daemon и НЕ пушится.

    На pull_request/merge_group публикации быть не должно: merge-коммит
    merge queue не должен получать теги в registry (аудит 2026-11-23).
    """
    build = workflow["jobs"]["build"]
    build_steps = _step_with(build, "docker/build-push-action")
    assert build_steps, "build job: нет шагов docker/build-push-action"
    loads = [step.get("with", {}).get("load") for step in build_steps]
    pushes = [step.get("with", {}).get("push") for step in build_steps]
    assert any(load is True for load in loads), (
        f"build job: docker/build-push-action должен иметь load: true "
        f"(без него scan-jobs не получит локальный образ), got loads={loads}"
    )
    assert all(push in (False, None) for push in pushes), (
        f"build job (ревью) не должен пушить в registry, got pushes={pushes}"
    )


def test_scan_job_uses_trivy(workflow: dict[str, Any]) -> None:
    """scan job использует aquasecurity/trivy-action."""
    scan = workflow["jobs"]["scan"]
    assert _uses_step(scan, "aquasecurity/trivy-action"), (
        "scan job должен использовать aquasecurity/trivy-action"
    )


def test_scan_job_severity_blocks_high_critical(workflow: dict[str, Any]) -> None:
    """scan job сканирует на HIGH+CRITICAL — иначе trivy не блокирует публикацию.

    Severity ``HIGH,CRITICAL`` — минимальный блокирующий порог для
    container image pipeline (LOW/MEDIUM — review, не gate).
    """
    for job_name in ("scan", "scan_release"):
        scan = workflow["jobs"][job_name]
        trivy_steps = _step_with(scan, "aquasecurity/trivy-action")
        assert trivy_steps, f"{job_name} job: нет шагов aquasecurity/trivy-action"
        severities = [step.get("with", {}).get("severity") for step in trivy_steps]
        matched = [
            s
            for s in severities
            if isinstance(s, str) and "HIGH" in s and "CRITICAL" in s
        ]
        assert matched, (
            f"{job_name} job: severity должен включать HIGH и CRITICAL "
            f"(иначе не блокирует публикацию), got severities={severities}"
        )


def test_scan_job_uploads_sarif(workflow: dict[str, Any]) -> None:
    """scan job загружает SARIF в Security tab (видимость для reviewer'ов)."""
    for job_name in ("scan", "scan_release"):
        scan = workflow["jobs"][job_name]
        assert _uses_step(scan, "github/codeql-action/upload-sarif"), (
            f"{job_name} job должен загружать trivy SARIF через "
            "github/codeql-action/upload-sarif (видимость в Security tab)"
        )


# ── ветка публикации: push по digest → scan → sign → verify → promote ───


def test_release_build_pushes_by_digest_without_tags(workflow: dict[str, Any]) -> None:
    """Публикация идёт ПО DIGEST: пользовательских тегов в registry нет.

    ``push-by-digest=true`` кладёт в registry только манифест по digest —
    теги (master/latest/sha-*) выдаются только после проверки подписи
    (job promote). Старая схема публиковала теги ДО скана и подписи, и
    пересобирала образ (просканированные байты ≠ опубликованные).
    """
    build = workflow["jobs"]["build_release"]
    build_steps = _step_with(build, "docker/build-push-action")
    assert build_steps, "build_release job: нет шагов docker/build-push-action"
    outputs = [str(step.get("with", {}).get("outputs", "")) for step in build_steps]
    assert any("push-by-digest=true" in out for out in outputs), (
        "build_release job: docker/build-push-action должен использовать "
        f"push-by-digest=true (иначе теги публикуются до проверки подписи), "
        f"got outputs={outputs}"
    )
    assert all(
        step.get("with", {}).get("tags") in (None, "") for step in build_steps
    ), "build_release job: не должен задавать пользовательские теги напрямую"


def test_scan_release_scans_the_signed_digest(workflow: dict[str, Any]) -> None:
    """Скан, подпись и публикация работают с ОДНИМ И ТЕМ ЖЕ digest'ом.

    Иначе «просканирован» один артефакт, а в registry ушёл другой.
    """
    scan = workflow["jobs"]["scan_release"]
    trivy_steps = _step_with(scan, "aquasecurity/trivy-action")
    assert trivy_steps, "scan_release job: нет шагов aquasecurity/trivy-action"
    refs = [str(step.get("with", {}).get("image-ref", "")) for step in trivy_steps]
    assert any("needs.build_release.outputs.digest" in ref for ref in refs), (
        "scan_release job: image-ref должен указывать на digest из "
        f"build_release, got refs={refs}"
    )
    for job_name in ("sign", "verify", "promote"):
        job = workflow["jobs"][job_name]
        runs = _job_text(job)
        assert "needs.build_release.outputs.digest" in runs, (
            f"{job_name} job должен оперировать digest'ом из build_release "
            "(иначе подписывается/публикуется другой артефакт)"
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


def test_sign_job_has_registry_write_permission(workflow: dict[str, Any]) -> None:
    """sign job имеет ``packages: write`` — подпись пишется в registry.

    Job-level ``permissions`` ЗАМЕНЯЮТ workflow-level, а не дополняют их:
    без ``packages: write`` в sign job'е cosign не сможет положить
    подпись в OCI (ошибка прав доступа, а не «нет токена»).
    """
    perms = workflow["jobs"]["sign"].get("permissions") or {}
    assert isinstance(perms, dict), "permissions job'а sign должен быть мапом"
    assert perms.get("packages") == "write", (
        "sign job: packages должен быть 'write' (подпись пишется в registry), "
        f"got perms={perms}"
    )


def test_promote_job_creates_tags_after_verify(workflow: dict[str, Any]) -> None:
    """Теги выдаются ТОЛЬКО после проверки подписи (job promote).

    До verify в registry лежит лишь манифест по digest — ни один
    пользовательский тег (master/latest/sha-*) не существует.
    """
    promote = workflow["jobs"]["promote"]
    needs_set = _needs_set(promote)
    assert "verify" in needs_set, (
        f"promote job должен depends_on: verify, got needs={sorted(needs_set)}"
    )
    runs = " ".join(_run_steps(promote))
    assert "imagetools create --tag" in runs, (
        "promote job должен создавать теги через "
        "'docker buildx imagetools create --tag' (перенос тега на "
        "проверенный digest), "
        f"got runs={runs!r}"
    )


def test_only_promote_issues_user_tags(workflow: dict[str, Any]) -> None:
    """Ни один job, кроме promote, не выдаёт пользовательские теги.

    Регрессия, которую закрывает проверка: теги появлялись в registry
    до скана и подписи (job push в старой схеме).
    """
    for job_name, job in workflow["jobs"].items():
        runs = " ".join(_run_steps(job))
        creates_tag = "imagetools create --tag" in runs
        if job_name == "promote":
            continue
        assert not creates_tag, (
            f"job '{job_name}' не должен выдавать пользовательские теги "
            "(это делает только promote — после verify)"
        )


# ── identity подписи ───────────────────────────────────────────────────


def test_verify_uses_anchored_identity_regexp(workflow: dict[str, Any]) -> None:
    """verify сверяет Subject по ЯКОРНОМУ regex, а не «любой репозиторий».

    Прежний ``https://github.com/.*/.*`` принимал подпись ЛЮБОГО workflow
    на github.com (независимое ревью 2026-11-23: MAJOR). Якорь обязателен:
    репозиторий + конкретный workflow + ref.
    """
    env = workflow.get("env") or {}
    pattern = env.get("COSIGN_IDENTITY_REGEXP")
    assert isinstance(pattern, str) and pattern, (
        "image.yml env.COSIGN_IDENTITY_REGEXP обязателен: verify должен "
        f"сверять identity по якорному regex, got env={env}"
    )
    assert pattern.startswith("^") and pattern.endswith("$"), (
        f"identity regex должен быть якоренным (^...$), got {pattern!r}"
    )
    assert ".*" not in pattern, (
        "identity regex не должен содержать '.*' (принимает подпись любого "
        f"репозитория), got {pattern!r}"
    )
    assert "gd_integration_tools" in pattern, (
        f"identity regex должен фиксировать репозиторий, got {pattern!r}"
    )
    assert ".github/workflows/image.yml" in pattern.replace("\\", ""), (
        f"identity regex должен фиксировать конкретный workflow, got {pattern!r}"
    )


def test_verify_step_passes_identity_regexp(workflow: dict[str, Any]) -> None:
    """verify передаёт identity regex в cosign и проверяет OIDC issuer."""
    verify = workflow["jobs"]["verify"]
    runs = " ".join(_run_steps(verify))
    assert "cosign verify" in runs, "verify job должен вызывать 'cosign verify'"
    assert "--certificate-identity-regexp" in runs, (
        "verify job должен передавать --certificate-identity-regexp в cosign, "
        f"got runs={runs!r}"
    )
    assert "--certificate-oidc-issuer" in runs, (
        "verify job должен передавать --certificate-oidc-issuer "
        f"(иначе принимается подпись от другого issuer), got runs={runs!r}"
    )


def test_identity_regexp_accepts_expected_subject(workflow: dict[str, Any]) -> None:
    """Регексп принимает Subject нашего workflow и оба регистра владельца.

    Проверка офлайн: реальный сертификат cosign в офлайн-окружении
    недоступен (нет OIDC/cosign) — поэтому проверяем сам регексп.
    """
    pattern = workflow["env"]["COSIGN_IDENTITY_REGEXP"]
    compiled = re.compile(pattern)
    assert compiled.match(EXPECTED_SUBJECT), (
        f"identity regex должен принимать Subject нашего workflow: "
        f"{EXPECTED_SUBJECT!r}, pattern={pattern!r}"
    )
    lowered = EXPECTED_SUBJECT.replace("IvanKorch1289", "ivankorch1289")
    assert compiled.match(lowered), (
        "identity regex должен принимать Subject с владельцем в нижнем "
        f"регистре (claim'ы GitHub могут быть lowercased): {lowered!r}"
    )


@pytest.mark.parametrize(
    "foreign_subject",
    [
        "https://github.com/attacker/evil/.github/workflows/image.yml@refs/heads/master",
        "https://github.com/IvanKorch1289/gd_integration_tools/"
        ".github/workflows/other.yml@refs/heads/master",
        "https://github.com/IvanKorch1289/gd_integration_tools/"
        ".github/workflows/image.yml@refs/heads/feature-x",
        "https://github.com/IvanKorch1289/gd_integration_tools/"
        ".github/workflows/image.yml@refs/tags/v1.2",
    ],
)
def test_identity_regexp_rejects_foreign_subjects(
    workflow: dict[str, Any], foreign_subject: str
) -> None:
    """Негативная проверка: чужая подпись не проходит verify.

    Офлайн-проверка регексп'а (реальная подпись в офлайне недоступна —
    ENV_BLOCKED). Чужой репозиторий, чужой workflow и недопустимый ref
    обязаны отвергаться.
    """
    pattern = workflow["env"]["COSIGN_IDENTITY_REGEXP"]
    compiled = re.compile(pattern)
    assert not compiled.match(foreign_subject), (
        f"identity regex не должен принимать чужой Subject: {foreign_subject!r}"
    )


# ── события: публикация только по push ─────────────────────────────────


@pytest.mark.parametrize("job_name", sorted(RELEASE_JOBS))
def test_release_jobs_only_on_push(workflow: dict[str, Any], job_name: str) -> None:
    """Ветка публикации запускается только на ``push``.

    Ни pull_request, ни merge_group не подписывают и не публикуют:
    merge-коммит merge queue — временный, теги в registry ему не нужны
    (аудит 2026-11-23).
    """
    condition = _job_if(workflow["jobs"][job_name])
    assert "github.event_name == 'push'" in condition, (
        f"job '{job_name}' должен запускаться только по push, got if={condition!r}"
    )
    assert "pull_request" not in condition, (
        f"job '{job_name}' не должен запускаться на pull_request, got if={condition!r}"
    )
    assert "merge_group" not in condition, (
        f"job '{job_name}' не должен запускаться на merge_group, got if={condition!r}"
    )


@pytest.mark.parametrize("job_name", sorted(RELEASE_JOBS))
def test_release_jobs_not_needed_by_review_branch(
    workflow: dict[str, Any], job_name: str
) -> None:
    """Ревью-ветка не зависит от ветки публикации."""
    for review_job in sorted(REVIEW_JOBS):
        needs_set = _needs_set(workflow["jobs"][review_job])
        assert job_name not in needs_set, (
            f"job '{review_job}' (ревью) не должен depends_on: {job_name} "
            f"(на PR публикации нет), got needs={sorted(needs_set)}"
        )


# ── pipeline ordering (depends_on) ─────────────────────────────────────


def test_scan_depends_on_build(workflow: dict[str, Any]) -> None:
    """scan ждёт build (нужен image тег/дайджест для trivy image scan)."""
    needs_set = _needs_set(workflow["jobs"]["scan"])
    assert "build" in needs_set, (
        f"scan job должен depends_on: build (нужен image тег), "
        f"got needs={sorted(needs_set)}"
    )


def test_scan_release_depends_on_build_release(workflow: dict[str, Any]) -> None:
    """scan_release ждёт build_release (нужен digest из registry)."""
    needs_set = _needs_set(workflow["jobs"]["scan_release"])
    assert "build_release" in needs_set, (
        f"scan_release job должен depends_on: build_release, "
        f"got needs={sorted(needs_set)}"
    )


def test_sign_depends_on_build_and_scan(workflow: dict[str, Any]) -> None:
    """sign ждёт build (образ в registry) и scan (блокирующая уязвимость).

    Порядок «push → sign» вынужден: cosign подписывает МАНИФЕСТ в registry,
    подписать ещё не запушенный образ технически невозможно.
    """
    needs_set = _needs_set(workflow["jobs"]["sign"])
    for required in ("build_release", "scan_release"):
        assert required in needs_set, (
            f"sign job должен depends_on: {required}, got needs={sorted(needs_set)}"
        )


def test_verify_depends_on_sign(workflow: dict[str, Any]) -> None:
    """verify ждёт sign — без подписи проверять нечего."""
    needs_set = _needs_set(workflow["jobs"]["verify"])
    assert "sign" in needs_set, (
        f"verify job должен depends_on: sign, got needs={sorted(needs_set)}"
    )


def test_signature_is_verified(workflow: dict[str, Any]) -> None:
    """verify job проверяет подпись запушенного образа.

    Это носитель гарантии «не выходит неподписанный образ»: workflow зелёный
    только если подпись предъявлена и проверена.
    """
    verify = workflow["jobs"]["verify"]
    has_verify_call = any(
        isinstance(step, dict)
        and isinstance(step.get("run"), str)
        and "cosign verify" in step["run"]
        for step in (verify.get("steps") or [])
    )
    assert has_verify_call, "verify job должен вызывать 'cosign verify'"
