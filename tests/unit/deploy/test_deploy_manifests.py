"""Offline-валидация deploy-манифестов (Sprint 171 / K-OPS-4 audit + Sprint 6 Devops 2).

Проверяет критичные deployment-blockers без поднятия Docker/k8s/Helm:

* module path, по которому стартует workflow worker, реально импортируется
  (``src.backend.infrastructure.workflow.worker``);
* compose и k8s манифесты не ссылаются на устаревший путь
  ``src.workflows.worker`` или ``src.backend.workflows.worker``;
* Helm Deployment для worker содержит явный ``command:``, иначе контейнер
  выполнит default image CMD (``python manage.py run`` → FastAPI вместо
  Temporal polling loop);
* Helm Job миграции передаёт ``-c alembic.ini`` — без этого Job зависит от
  WORKDIR образа и ломается при пересборке с другим WORKDIR;
* ``deploy/helm/gd-integration-tools/values.yaml`` и
  ``deploy/k8s/deployment-app.yaml`` консистентны по ``runAsUser/Group/fsGroup``
  (Sprint 6 Devops 2 audit) — drift между ними вызывает permission-failures
  с ``readOnlyRootFilesystem: true`` (см. S204 retro-audit B03);
* Helm-шаблон ``servicemonitor.yaml`` для Prometheus Operator содержит
  корректные selector/endpoints/port и opt-in через ``.Values.serviceMonitor``.

Использует ``yaml.safe_load`` для compose/k8s (чистый YAML) и
``yaml.safe_load_all`` поверх regex-strip ``{{ ... }}`` для Helm-шаблонов —
Helm CLI не установлен в тестовой среде, а офлайн-проверка структуры не
требует рендеринга values.
"""


from __future__ import annotations

import importlib.util
import re
from pathlib import Path
from typing import Any

import pytest
import yaml

# ── Константы путей ────────────────────────────────────────────────────

PROJECT_ROOT: Path = Path(__file__).resolve().parents[3]

WORKER_MODULE: str = "src.backend.infrastructure.workflow.worker"
WORKER_FILE: Path = (
    PROJECT_ROOT / "src" / "backend" / "infrastructure" / "workflow" / "worker.py"
)

COMPOSE_FILE: Path = PROJECT_ROOT / "ops" / "compose" / "docker-compose.yml"
COMPOSE_LIGHT_FILE: Path = PROJECT_ROOT / "ops" / "compose" / "docker-compose.light.yml"
K8S_WORKER_FILE: Path = PROJECT_ROOT / "deploy" / "k8s" / "deployment-worker.yaml"
K8S_APP_FILE: Path = PROJECT_ROOT / "deploy" / "k8s" / "deployment-app.yaml"
HELM_VALUES_FILE: Path = (
    PROJECT_ROOT / "deploy" / "helm" / "gd-integration-tools" / "values.yaml"
)
HELM_WORKER_FILE: Path = (
    PROJECT_ROOT
    / "deploy"
    / "helm"
    / "gd-integration-tools"
    / "templates"
    / "deployment-worker.yaml"
)
HELM_MIGRATION_FILE: Path = (
    PROJECT_ROOT
    / "deploy"
    / "helm"
    / "gd-integration-tools"
    / "templates"
    / "job-migration.yaml"
)
HELM_SERVICEMONITOR_FILE: Path = (
    PROJECT_ROOT
    / "deploy"
    / "helm"
    / "gd-integration-tools"
    / "templates"
    / "servicemonitor.yaml"
)

# Устаревшие пути, которые в любых deploy-манифестах считаем deployment-blocker.
# Зафиксированы в Sprint 171 K-OPS-4 audit (2026-08-03): оба модуля реально
# отсутствуют, контейнер падает в CrashLoopBackOff.
DEPRECATED_WORKER_PATHS: frozenset[str] = frozenset(
    {"src.workflows.worker", "src.backend.workflows.worker"},
)


# ── Helpers ────────────────────────────────────────────────────────────


def _strip_helm_template(text: str) -> str:
    """Удаляет ``{{ ... }}`` блоки Go-template для офлайн-YAML-парсинга.

    Helm не установлен в test-env, но структурную валидацию (kind/apiVersion/
    containers/command/job spec) можно делать и без рендера values. Заменяем
    любые ``{{ ... }}`` на пустую строку — yaml после этого парсится чисто.
    """
    return re.sub(r"\{\{[^}]*\}\}", "", text)


def _load_yaml(path: Path) -> Any:
    """Безопасная загрузка YAML (поддерживает multi-document)."""
    raw = path.read_text(encoding="utf-8")
    return list(yaml.safe_load_all(raw))


def _load_helm_yaml(path: Path) -> list[dict[str, Any]]:
    """Загрузка Helm-шаблона: strip Go-template → safe_load_all."""
    raw = _strip_helm_template(path.read_text(encoding="utf-8"))
    return [doc for doc in yaml.safe_load_all(raw) if doc is not None]


# ── Worker module integrity ────────────────────────────────────────────


def test_worker_module_path_resolves() -> None:
    """``src.backend.infrastructure.workflow.worker`` импортируется."""
    assert WORKER_FILE.exists(), f"Worker module file missing: {WORKER_FILE}"
    spec = importlib.util.find_spec(WORKER_MODULE)
    assert spec is not None, f"Module {WORKER_MODULE} cannot be located"
    assert spec.origin == str(WORKER_FILE), (
        f"Spec origin {spec.origin} != expected {WORKER_FILE}"
    )


def test_worker_module_exposes_main() -> None:
    """Worker module предоставляет ``main()`` для console-script.

    Используем ``ast`` вместо ``importlib.exec_module``: exec_module без
    регистрации в ``sys.modules`` падает в dataclass-интроспекции при загрузке
    pydantic-моделей (см. ``src.backend.core.domain.models.__init__``), а
    полный ``import`` тянет всю settings-цепочку и валится при отсутствии
    Vault/БД. AST-парсинг — дешёвая structural-проверка без side-effects.
    """
    import ast

    source = WORKER_FILE.read_text(encoding="utf-8")
    tree = ast.parse(source)
    function_names: set[str] = {
        node.name
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))
    }
    assert "main" in function_names, (
        f"{WORKER_FILE} must define top-level ``main()`` for python -m entry-point"
    )


# ── docker-compose.yml ─────────────────────────────────────────────────


@pytest.fixture(scope="module")
def compose_main() -> dict[str, Any]:
    docs = _load_yaml(COMPOSE_FILE)
    assert docs, f"{COMPOSE_FILE} is empty"
    return docs[0]


def test_compose_main_yamls(compose_main: dict[str, Any]) -> None:
    assert "services" in compose_main
    assert "workflow-worker" in compose_main["services"]


def test_compose_main_worker_entrypoint(compose_main: dict[str, Any]) -> None:
    """``workflow-worker`` использует корректный module path."""
    worker = compose_main["services"]["workflow-worker"]
    entrypoint = worker.get("entrypoint") or []
    flat: list[str] = []
    for item in entrypoint:
        if isinstance(item, str):
            flat.append(item)
    assert flat, "workflow-worker must declare entrypoint"
    joined = " ".join(flat)
    assert WORKER_MODULE in joined, (
        f"workflow-worker entrypoint '{joined}' must reference {WORKER_MODULE}"
    )
    for deprecated in DEPRECATED_WORKER_PATHS:
        assert deprecated not in joined, (
            f"workflow-worker entrypoint still uses deprecated path {deprecated}"
        )


# ── docker-compose.light.yml ──────────────────────────────────────────


@pytest.fixture(scope="module")
def compose_light() -> dict[str, Any]:
    docs = _load_yaml(COMPOSE_LIGHT_FILE)
    assert docs, f"{COMPOSE_LIGHT_FILE} is empty"
    return docs[0]


def test_compose_light_worker_command(compose_light: dict[str, Any]) -> None:
    """Light-worker command ссылается на реальный worker module path."""
    worker = compose_light["services"]["workflow-worker"]
    command = worker.get("command") or []
    flat: list[str] = []
    for item in command:
        if isinstance(item, str):
            flat.append(item)
    joined = " ".join(flat)
    assert joined.strip(), "workflow-worker must declare command"
    assert WORKER_MODULE in joined, (
        f"workflow-worker command '{joined}' must reference {WORKER_MODULE}"
    )
    for deprecated in DEPRECATED_WORKER_PATHS:
        assert deprecated not in joined, (
            f"workflow-worker command still uses deprecated path {deprecated}"
        )


def test_compose_light_healthcheck_uses_real_module(
    compose_light: dict[str, Any],
) -> None:
    """Light-worker healthcheck grep'ает актуальный module path."""
    worker = compose_light["services"]["workflow-worker"]
    healthcheck = worker.get("healthcheck") or {}
    test_list = healthcheck.get("test") or []
    joined = " ".join(str(t) for t in test_list)
    assert "workflows.worker" not in joined or WORKER_MODULE in joined, (
        f"healthcheck '{joined}' greps stale 'workflows.worker' substring"
    )


# ── k8s deployment-worker.yaml ────────────────────────────────────────


@pytest.fixture(scope="module")
def k8s_worker() -> dict[str, Any]:
    docs = _load_yaml(K8S_WORKER_FILE)
    assert docs, f"{K8S_WORKER_FILE} is empty"
    return docs[0]


def test_k8s_worker_command_module(k8s_worker: dict[str, Any]) -> None:
    """k8s worker Deployment.command ссылается на реальный worker module path."""
    containers = k8s_worker["spec"]["template"]["spec"]["containers"]
    assert containers, "Deployment must have at least one container"
    command = containers[0].get("command") or []
    joined = " ".join(str(c) for c in command)
    assert joined.strip(), "worker container must declare command"
    assert WORKER_MODULE in joined, (
        f"k8s worker command '{joined}' must reference {WORKER_MODULE}"
    )
    for deprecated in DEPRECATED_WORKER_PATHS:
        assert deprecated not in joined, (
            f"k8s worker command still uses deprecated path {deprecated}"
        )


# ── Helm deployment-worker.yaml ───────────────────────────────────────


def test_helm_worker_command_present() -> None:
    """Helm worker Deployment имеет явный ``command:`` (иначе — default CMD,
    который для FastAPI-образа запустит ``python manage.py run`` вместо polling).
    """
    docs = _load_helm_yaml(HELM_WORKER_FILE)
    assert docs, f"{HELM_WORKER_FILE} is empty after strip"
    deployment = docs[0]
    assert deployment["kind"] == "Deployment", (
        f"Expected Deployment, got {deployment.get('kind')}"
    )
    containers = deployment["spec"]["template"]["spec"]["containers"]
    assert containers, "Helm worker Deployment must have at least one container"
    command = containers[0].get("command") or []
    assert command, (
        "Helm worker Deployment must override command: default image CMD "
        "starts FastAPI app, not the Temporal polling loop."
    )
    joined = " ".join(str(c) for c in command)
    assert WORKER_MODULE in joined, (
        f"Helm worker command '{joined}' must reference {WORKER_MODULE}"
    )
    for deprecated in DEPRECATED_WORKER_PATHS:
        assert deprecated not in joined, (
            f"Helm worker command still uses deprecated path {deprecated}"
        )


# ── Helm job-migration.yaml ───────────────────────────────────────────


def test_helm_migration_job_alembic_config() -> None:
    """Helm migration Job передаёт ``-c alembic.ini`` alembic'у.

    ``python -m alembic upgrade head`` без ``-c`` зависит от CWD = /app;
    явный ``-c alembic.ini`` делает Job идемпотентным относительно WORKDIR и
    совпадает с ``deploy/k8s/jobs/migration.yaml`` (k8s Job).
    """
    docs = _load_helm_yaml(HELM_MIGRATION_FILE)
    assert docs, f"{HELM_MIGRATION_FILE} is empty after strip"
    job = docs[0]
    assert job["kind"] == "Job", f"Expected Job, got {job.get('kind')}"
    containers = job["spec"]["template"]["spec"]["containers"]
    command = containers[0].get("command") or []
    assert command, "Helm migration Job must declare command"
    joined = " ".join(command)
    assert "alembic" in joined, f"command '{joined}' must invoke alembic"
    assert "-c" in joined, (
        f"command '{joined}' must pass -c alembic.ini to make alembic config "
        f"explicit (avoids implicit CWD lookup)"
    )
    assert "alembic.ini" in joined, (
        f"command '{joined}' must reference alembic.ini config file"
    )
    assert "upgrade" in joined and "head" in joined, (
        f"command '{joined}' must include 'upgrade head'"
    )


# ── Helm secret.yaml — sanity check (не трогаем placeholder'ы) ────────


def test_helm_secret_template_is_template_only() -> None:
    """Helm Secret помечен как template; placeholder-значения допустимы.

    Этот тест защищает от регрессий, при которых кто-то по ошибке вставит
    реальный секрет в коммит. Допустимые placeholder-patterns:

    * пустая строка;
    * ``CHANGEME`` / ``placeholder-*`` / ``placeholder-set-via-vault``;
    * ``None`` — означает, что значение собирается из ``{{ printf ... }}``
      и убирается regex'ом, применяемым для offline-парсинга (см.
      ``_strip_helm_template``).

    Любое значение, не подпадающее под эти шаблоны, считается подозрительным
    (эвристика; false-positive'ы неизбежны для коротких тестовых строк).
    """
    helm_secret: Path = (
        PROJECT_ROOT
        / "deploy"
        / "helm"
        / "gd-integration-tools"
        / "templates"
        / "secret.yaml"
    )
    raw = _strip_helm_template(helm_secret.read_text(encoding="utf-8"))
    docs = [d for d in yaml.safe_load_all(raw) if d is not None]
    assert docs, "Helm Secret template must declare at least one document"
    secret = docs[0]
    assert secret["kind"] == "Secret"
    string_data = secret.get("stringData") or {}
    assert string_data, "Helm Secret template must declare stringData placeholders"

    placeholder_patterns = (
        re.compile(r"^$"),
        re.compile(r"^CHANGEME$"),
        re.compile(r"^placeholder[-_].*$"),
        re.compile(r"^placeholder-set-via-vault$"),
    )
    suspicious: list[tuple[str, str]] = []
    for key, value in string_data.items():
        if value is None:
            # ``None`` = значение собрано из Go-template ``{{ printf ... }}``,
            # offline-stripper не может его восстановить без values.yaml —
            # пропускаем как валидный placeholder.
            continue
        if isinstance(value, str) and any(p.match(value) for p in placeholder_patterns):
            continue
        suspicious.append((key, str(value)[:64]))
    assert not suspicious, (
        "Helm Secret содержит не-placeholder значения; "
        "production секреты должны приходить из ExternalSecrets+Vault: "
        f"{suspicious}"
    )


# ── Sprint 6 Devops 2: consistency audit (values.yaml ↔ k8s raw) ──────


@pytest.fixture(scope="module")
def k8s_app_deployment() -> dict[str, Any]:
    """Первый документ ``deploy/k8s/deployment-app.yaml`` (Deployment)."""
    docs = _load_yaml(K8S_APP_FILE)
    assert docs, f"{K8S_APP_FILE} is empty"
    deployment = docs[0]
    assert deployment["kind"] == "Deployment", (
        f"Expected Deployment, got {deployment.get('kind')}"
    )
    return deployment


@pytest.fixture(scope="module")
def helm_security_ctx() -> dict[str, Any]:
    """``securityContext:`` из ``values.yaml`` (source-of-truth для Helm)."""
    docs = _load_yaml(HELM_VALUES_FILE)
    assert docs, f"{HELM_VALUES_FILE} is empty"
    values = docs[0]
    assert isinstance(values.get("securityContext"), dict), (
        f"{HELM_VALUES_FILE} must declare top-level securityContext"
    )
    return values["securityContext"]


def test_k8s_app_runasuser_matches_values(
    k8s_app_deployment: dict[str, Any], helm_security_ctx: dict[str, Any],
) -> None:
    """``runAsUser/Group/fsGroup`` в raw k8s deployment совпадают с values.yaml.

    Sprint 6 Devops 2 audit: drift между raw k8s и Helm values вызывает
    permission-failures при ``readOnlyRootFilesystem: true`` (см. S204
    retro-audit B03 — было 1000 в обоих местах, должно быть 10001 = uid
    appuser из ``ops/compose/Dockerfile``).
    """
    pod_security = k8s_app_deployment["spec"]["template"]["spec"]["securityContext"]
    for key in ("runAsUser", "runAsGroup", "fsGroup"):
        raw_value = pod_security.get(key)
        values_value = helm_security_ctx.get(key)
        assert raw_value is not None, (
            f"k8s deployment-app.yaml pod.securityContext must declare {key}"
        )
        assert values_value is not None, (
            f"values.yaml securityContext must declare {key}"
        )
        assert raw_value == values_value, (
            f"Sprint 6 Devops 2 consistency: {key} drift between "
            f"{K8S_APP_FILE} ({raw_value}) and {HELM_VALUES_FILE} "
            f"({values_value}); values.yaml + Dockerfile are source of truth"
        )


def test_k8s_app_probes_match_helm_values(k8s_app_deployment: dict[str, Any]) -> None:
    """Параметры probes в raw k8s совпадают с ``values.yaml`` probes.

    Sprint 6 Devops 2 audit: явная проверка ``failureThreshold``/``periodSeconds``
    /``initialDelaySeconds``/``timeoutSeconds`` для startup/readiness/liveness —
    drift ломает rolling-update (liveness слишком агрессивен → CrashLoopBackOff).
    """
    docs = _load_yaml(HELM_VALUES_FILE)
    values_probes: dict[str, Any] = docs[0]["app"]["probes"]

    container = k8s_app_deployment["spec"]["template"]["spec"]["containers"][0]

    # startupProbe
    startup = container.get("startupProbe") or {}
    assert (
        startup.get("failureThreshold") == values_probes["startupFailureThreshold"]
    ), "startupProbe.failureThreshold drift"
    assert startup.get("periodSeconds") == values_probes["startupPeriodSeconds"], (
        "startupProbe.periodSeconds drift"
    )

    # readinessProbe
    readiness = container.get("readinessProbe") or {}
    assert (
        readiness.get("initialDelaySeconds") == values_probes["readinessInitialDelay"]
    ), "readinessProbe.initialDelaySeconds drift"
    assert readiness.get("periodSeconds") == values_probes["readinessPeriodSeconds"], (
        "readinessProbe.periodSeconds drift"
    )
    assert readiness.get("timeoutSeconds") == values_probes["readinessTimeout"], (
        "readinessProbe.timeoutSeconds drift"
    )
    assert (
        readiness.get("failureThreshold") == values_probes["readinessFailureThreshold"]
    ), "readinessProbe.failureThreshold drift"

    # livenessProbe
    liveness = container.get("livenessProbe") or {}
    assert (
        liveness.get("initialDelaySeconds") == values_probes["livenessInitialDelay"]
    ), "livenessProbe.initialDelaySeconds drift"
    assert liveness.get("periodSeconds") == values_probes["livenessPeriodSeconds"], (
        "livenessProbe.periodSeconds drift"
    )
    assert liveness.get("timeoutSeconds") == values_probes["livenessTimeout"], (
        "livenessProbe.timeoutSeconds drift"
    )
    assert (
        liveness.get("failureThreshold") == values_probes["livenessFailureThreshold"]
    ), "livenessProbe.failureThreshold drift"


# ── Sprint 6 Devops 2: Helm ServiceMonitor для Prometheus Operator ─────


def test_helm_servicemonitor_template_exists() -> None:
    """Файл шаблона существует и валиден как Helm-template."""
    assert HELM_SERVICEMONITOR_FILE.exists(), (
        f"Helm ServiceMonitor template missing: {HELM_SERVICEMONITOR_FILE}"
    )
    raw = HELM_SERVICEMONITOR_FILE.read_text(encoding="utf-8")
    # Helm Go-template syntax валидна хотя бы поверхностно (есть if/action).
    assert "{{" in raw and "}}" in raw, (
        f"{HELM_SERVICEMONITOR_FILE} must contain Go-template directives"
    )


def test_helm_servicemonitor_structure_and_selector() -> None:
    """ServiceMonitor содержит правильный kind, apiVersion, selector и endpoints.

    Sprint 6 Devops 2: ``selector.matchLabels`` должен совпадать с labels
    ``Service gd-app`` (``templates/service-app.yaml``); ``endpoints[].port``
    — имя порта из Service (`metrics`); ``endpoints[].path`` — фактический
    scrape-path контейнера. Без этого Prometheus Operator не подберёт target.
    """
    docs = _load_helm_yaml(HELM_SERVICEMONITOR_FILE)
    assert docs, f"{HELM_SERVICEMONITOR_FILE} is empty after strip"
    sm = docs[0]
    assert sm["kind"] == "ServiceMonitor", (
        f"Expected ServiceMonitor, got {sm.get('kind')}"
    )
    assert sm["apiVersion"] == "monitoring.coreos.com/v1", (
        f"Expected apiVersion monitoring.coreos.com/v1, got {sm.get('apiVersion')}"
    )

    # Selector must match Service gd-app labels.
    selector = sm["spec"]["selector"]["matchLabels"]
    assert selector == {
        "app.kubernetes.io/name": "gd-integration-tools",
        "app.kubernetes.io/component": "app",
    }, f"ServiceMonitor selector must match Service gd-app labels, got {selector}"

    # Namespace selector ограничивает lookup указанным namespace.
    # Offline-stripper убирает ``{{ .Values.namespace.name }}`` → пустая строка,
    # поэтому проверяем только что список непустой (значение само придёт из
    # values при рендере через helm install).
    ns_selector = sm["spec"]["namespaceSelector"]["matchNames"]
    assert isinstance(ns_selector, list) and len(ns_selector) >= 1, (
        f"namespaceSelector.matchNames must declare at least one namespace, got {ns_selector}"
    )

    # Endpoints: port/path обязательны (static), interval/timeout —
    # templated через values, offline-stripper оставляет ``None``;
    # проверяем только наличие ключа.
    endpoints = sm["spec"]["endpoints"]
    assert endpoints, "ServiceMonitor must declare at least one endpoint"
    ep = endpoints[0]
    assert ep["port"] == "metrics", (
        f"endpoints[0].port must reference Service port name 'metrics', got {ep.get('port')}"
    )
    assert ep["path"] == "/metrics", (
        f"endpoints[0].path must be '/metrics', got {ep.get('path')}"
    )
    assert "interval" in ep, "endpoints[0].interval required (templated)"
    assert "scrapeTimeout" in ep, "endpoints[0].scrapeTimeout required (templated)"


def test_helm_servicemonitor_opt_in_flag() -> None:
    """ServiceMonitor рендерится только при ``.Values.serviceMonitor.enabled``.

    Opt-out через values.yaml — критично для кластеров без Prometheus Operator
    (например, dev_light); template-guard ``{{- if ... }}`` обязателен.
    """
    raw = HELM_SERVICEMONITOR_FILE.read_text(encoding="utf-8")
    assert ".Values.serviceMonitor" in raw, (
        "ServiceMonitor template must guard rendering via .Values.serviceMonitor.*"
    )
    # Должен быть как минимум один ``if`` директив, ссылающийся на enabled-флаг.
    assert re.search(r"\{\{-?\s*if\s+[^}]*\.Values\.serviceMonitor\.enabled", raw), (
        "ServiceMonitor template must use {{- if .Values.serviceMonitor.enabled ... }} guard"
    )


def test_helm_servicemonitor_default_release_label() -> None:
    """Default label ``release: prometheus`` для kube-prometheus-stack.

    Prometheus CR с ``serviceMonitorSelector: matchLabels: {release: prometheus}``
    подбирает ServiceMonitor только с этой меткой. Дефолт hardcoded в
    шаблоне (``| default "prometheus"``) — проверяем наличие через regex,
    чтобы тест не зависел от рендера values.
    """
    raw = HELM_SERVICEMONITOR_FILE.read_text(encoding="utf-8")
    assert "prometheus" in raw, (
        "ServiceMonitor template must reference 'prometheus' (default release label "
        "for kube-prometheus-stack serviceMonitorSelector)"
    )
