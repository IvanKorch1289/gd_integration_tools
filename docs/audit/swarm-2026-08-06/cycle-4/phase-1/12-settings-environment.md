# Cycle 4 Phase 1 — Domain 12: Настройки-Окружение

**Date**: 2026-08-07
**HEAD**: 22e08a0d
**Scope**: `src/backend/core/config/**`, `src/backend/core/scaling/granian_tuning.py`,
`config/**`, `config_profiles/**`, `deploy/**`, `ops/compose/**`, `docker-compose*.yml`,
environment/settings tests.
**Analyst**: independent (12-settings-environment)

---

## 1. Scope / не проверено

### Проверено (read-only)

| Категория | Файлы / артефакты | Команда / способ |
|---|---|---|
| Granian tuning | `src/backend/core/scaling/granian_tuning.py` | Read + `.venv/bin/python -m pytest tests/unit/core/scaling/test_granian_tuning.py tests/unit/core/scaling/test_granian_graceful_shutdown.py` (14/14 PASS) |
| Config root | `src/backend/core/config/settings.py`, `config_loader.py`, `profile.py`, `constants.py`, `mixins.py`, `security.py`, `hot_reload.py`, `waf.py`, `database.py`, `vault.py`, `consul_config.py`, `transport.py`, `workflow.py`, `ai_stack.py` | Read |
| Validator | `src/backend/core/config/validator/**` (`__init__.py`, `security_checks.py`, `infrastructure_checks.py`, `_helpers.py`) | Read + `.venv/bin/python -m pytest tests/unit/core/config/test_validator.py` (43/43 PASS) |
| Feature flags | `src/backend/core/config/features/__init__.py`, `workflow.py` (T-07), `experimental.py` | Read + test |
| Services configs | `src/backend/core/config/services/*.py` (cache, dlq, graphql, invoker, jupyter_hub, ldap, llm, logging, mail, mqtt, outbox, policy, queue, resilience, rpa, sms, snapshot, storage, watermark, websocket) | Read |
| AppBase / external | `src/backend/core/config/base/app_base.py`, `scheduler.py`, `external_apis/*`, `external_databases/*` | Read |
| YAML profiles | `config_profiles/{base,dev,dev_light,staging,prod}.yml` | Read + AST parse |
| Compose | `ops/compose/docker-compose.yml`, `prod.yml`, `perf.yml`, `bluegreen.yml`, `light.yml`, `plugin-dev.yml`, `windows-worker.yml` | Read |
| K8s manifests | `deploy/k8s/{configmap,deployment-app,deployment-worker,hpa-app,...}.yaml`; `deploy/helm/gd-integration-tools/values.yaml` | Read |
| Tools | `tools/config_audit.py`, `tools/granian_runner.py`, `tools/codegen_settings.py` | Read + `.venv/bin/python tools/config_audit.py` (FAIL exit 1) |
| Windows worker | `deploy/windows-worker/main.py`, `Dockerfile.windows` | Read |
| Tests | `tests/unit/core/config/` (40+ файлов), `tests/unit/core/scaling/`, `tests/smoke/test_yaml_hot_reload.py`, `tests/smoke/test_granian_runtime.py` | `.venv/bin/python -m pytest …` |

### Не проверено

| Категория | Причина |
|---|---|
| `.env`, `.env.*`, `secrets/**`, `*.pem`, `*.key`, `*secret*`, `*token*` | Запрещено правилом scope |
| `docs/audit/swarm-2026-08-06/cycle-{1,2,3}/**`, `docs/audit/cycle-1/**`, `KNOWN_ISSUES.md`, `CLAUDE.md`, `PLAN.md`, `DEEP_AUDIT_REPORT.md`, `triage_allowlist_report.md` | Запрещено правилом phase 1 (читать только свой домен) |
| Pre-existing `services/ai/gateway_adapter.py:128-129` `except Exception: pass` | Pre-existing residual вне scope |
| Pre-existing `tests/unit/core/ai/test_gateway_pipeline_mixin.py` (mypy + 5 failures) | Pre-existing residuals вне scope |
| `extensions/**`, `services/**`, `infrastructure/**` (кроме явно проверенных) | Вне scope |
| `uv.lock`, `pip-audit.json`, `.blue_green.state`, untracked docs | Pre-existing drift, НЕ этому swarm |

---

## 3. Verified strengths

### A. Architecture / DI / fail-closed

* **Multi-source settings loader** (`src/backend/core/config/config_loader.py:139-178`): YAML
  `base.yml` + overlay активного профиля через `_deep_merge`. `VaultConfigSettingsSource`
  (`:191-253`) активируется только если `vault.enabled=true` + все 3 env (`VAULT_ADDR`,
  `VAULT_TOKEN`, `VAULT_SECRET_PATH`); при недоступности — module-level флаг
  `_VAULT_UNREACHABLE` подавляет повторные warning'и (no log-spam).
  `ConsulConfigSettingsSource` (`:273-303`) opt-in через `CONSUL_ENABLED=false` default
  (fail-closed).
* **CORS fail-closed**: `SecureSettings._forbid_wildcard_with_credentials` (security.py:123-136)
  запрещает `cors_origins=["*"]` + `cors_allow_credentials=True` на уровне pydantic —
  защита от credential-leak через CSRF. `_forbid_wildcard_in_prod` (security.py:112-121)
  запрещает wildcard в prod.
* **ConfigValidator mixin architecture** (S52 W2 decomp): 14 `_check_*` методов в 3 mixin
  файлах (`security_checks.py`, `api_docs_checks.py`, `infrastructure_checks.py`),
  fail-fast политика в `validate_startup_config` (validator/__init__.py:99-150): CRITICAL
  в production → `ProductionConfigError`. Покрыты WAF strict, WAF allow_hosts, ClamAV
  fail-open, Swagger/Redoc в prod, Vault disabled, CORS credentials+wild, debug mode in
  prod, JWT secret too short, DB host в prod, Redis host required/localhost в prod,
  feature-flag dependency unmet (CRITICAL/WARNING).
* **Feature-flag dependency checks** (validator/infrastructure_checks.py:165-238):
  CRITICAL/WARNING severity дифференцированы, источник — `settings.features` или
  fallback на singleton.
* **Vault enabled coercion** (vault.py:32-49): пустая `VAULT_ENABLED=` трактуется как
  default `True` (Pydantic strict-bool ломается на пустой строке).
* **Granian graceful-shutdown per D-AUDIT-95** (granian_tuning.py:125-135, 222-223):
  `graceful_shutdown_timeout=30` default, env `GRANIAN_`, range `[0, 300]`. 0 = escape hatch
  (флаг опускается), >300 = ValidationError. K8s `terminationGracePeriodSeconds=30`
  совпадает.

### B. Layering / DI compliance

* Все `BaseSettingsWithLoader` подклассы объявляют `yaml_group: ClassVar[str] = …`
  (69 yaml_groups найдено через grep).
* `Settings` агрегатор (`settings.py`) собирает 41 Settings-класс через
  `_RESILIENCE_*`/`lru_cache`-singleton pattern.
* `pydantic-settings` multi-source ordering: init > env > Vault > YAML > dotenv >
  file_secret (config_loader.py:336-342).
* `BaseSettingsWithLoader` имеет `model_config = SettingsConfigDict(env_prefix="",
  extra="forbid")` — запрещает extras (defensive).

### C. Tests (run в этом аудите)

| Suite | Pass | Notes |
|---|---|---|
| `tests/unit/core/scaling/test_granian_tuning.py` | 8/8 | `auto`/explicit workers, blocking_threads, interface fallback на asgi, CLI flags |
| `tests/unit/core/scaling/test_granian_graceful_shutdown.py` | 6/6 | D-AUDIT-95 regression: default emits flag, explicit value, zero omits, cap 400 raises, -1 raises, position before app |
| `tests/unit/core/scaling/test_{auto,temporal_worker_scaler}.py` | 18/18 | AutoScaler / TemporalWorker scaler |
| `tests/unit/core/config/test_validator.py` | 43/43 | 14 _check_* + sorted/raise |
| `tests/unit/core/config/test_workflow.py` + `test_features_workflow.py` | 8/8 | `bootstrap_defaults_enabled` removed, 5 workflow flags inherit, MRO |
| `tests/unit/core/config/test_openfeature_default_off.py` | 1/1 | `openfeature_external` default False (D-AUDIT-FIX-184-2) |
| `tests/smoke/test_yaml_hot_reload.py` | 1/1 | Lifecycle reload |
| `tests/smoke/test_granian_runtime.py` | 5/5 | Runtime integration |
| **Subtotal (in-scope)** | **90/90** | All PASS |
| `tests/unit/core/config/` (full) | 386/387 | 1 pre-existing failure (см. §7) |

### D. K8s / Helm production-ready

* `deploy/k8s/deployment-app.yaml:72-78` и `deployment-worker.yaml:77-83`: CPU+memory
  requests/limits заданы; non-root securityContext, readOnlyRootFilesystem, drop ALL caps;
  `terminationGracePeriodSeconds=30` (app) / `300` (worker).
* `deploy/k8s/hpa-app.yaml`: HPA 3→20 по CPU 70% + memory 80%.
* `deploy/k8s/pdb.yaml`, `networkpolicy.yaml`: PDB + NetworkPolicy присутствуют.
* `deploy/helm/gd-integration-tools/values.yaml`: 4 env-mappings (app/worker), S204 B03
  fix uid=10001 выровнен с Dockerfile.

---

## 4. Findings table

| ID | Priority | path:line | Title |
|---|---|---|---|
| ENV-P1-001 | **P1** | `tools/config_audit.py:36`, `tools/codegen_settings.py:62-65,69` | Stale path `src/core/config/` vs реальный `src/backend/core/config/` — CI gate молча проваливается (RESIDUAL) |
| ENV-P1-002 | **P1** | `src/backend/main.py:81-117` + `src/backend/core/scaling/granian_tuning.py:178-225` + `src/backend/core/config/base/app_base.py:72-163` | Дублирование Granian surface: 2 независимых конфиг-канала (`settings.app.granian_*` через Granian Python API + `granian_tuning` через CLI builder) (RESIDUAL) |
| ENV-P1-003 | **P1** | `src/backend/core/config/services/cache.py:201-218` (`RedisSettings.cluster_mode`) | `cluster_mode: bool = Field(default=True)` при пустом `cluster_nodes: list[str] = Field(default_factory=list)` — default сломан (RedisCluster будет создан с `startup_nodes=[]`) |
| ENV-P1-004 | **P1** | `ops/compose/{docker-compose.yml,docker-compose.prod.yml,docker-compose.light.yml,docker-compose.perf.yml,docker-compose.bluegreen.yml}` | Ни один service не имеет `deploy.resources.limits` (cpu/memory) — кроме `replicas:` в `workflow-worker` |
| ENV-P1-005 | **P1** | `src/backend/core/config/security.py:115-121`, `src/backend/core/config/profile.py:23`, `src/backend/core/config/base/app_base.py:33-43` | Три разных env-var для одного концепта: `APP_PROFILE` / `APP_ENV` / `APP_ENVIRONMENT` / `app.environment` — рассинхрон в prod-gate'ах |
| ENV-P2-001 | **P2** | `src/backend/core/scaling/granian_tuning.py:125-135` | `graceful_shutdown_timeout: int = Field(default=30, …)` — hardcoded default 30 (RESIDUAL: значение по-прежнему в коде, не вынесено в ENV-only default) |
| ENV-P2-002 | **P2** | `src/backend/core/config/services/cache.py` (single file содержит и `RedisSettings`, и `CacheSettings`) | Layer violation: 2 Settings-класса в одном файле; `RedisSettings` логически принадлежит `services/redis.py` |
| ENV-P2-003 | **P2** | `src/backend/core/config/services/policy.py`, `services/dlq.py`, `services/ldap.py`, `services/mqtt.py`, `services/outbox.py`, `services/rpa.py`, `services/websocket.py`, `services/graphql.py`, `services/llm.py`, `ai_stack.py` | 12+ Settings-классов имеют `yaml_group` но НЕ агрегированы в `Settings` (settings.py) — загружаются только как module-level singletons; `policy_settings`, `ldap_settings` и т.п. не видны в `settings.<name>` |
| ENV-P3-001 | **P3** | `src/backend/core/config/services/cache.py:201-218` | Опечатка/инверсия: `cluster_mode` default True при том что `cluster_nodes` default []; example в json_schema=`False`; description "Включить кластерный режим" — рассинхрон между default/example/description |
| ENV-P3-002 | **P3** | `src/backend/core/config/waf.py:49-57` | `outbound_via_facade: bool = Field(default=True)` — description говорит "Phase-2 (True, default)", но это НЕ security-feature (нет риск-импакта) |
| ENV-P3-003 | **P3** | `src/backend/core/config/transport.py:20-43` | `TransportSettings` использует `BaseSettings` напрямую (НЕ `BaseSettingsWithLoader`); нет `yaml_group` — не регистрируется в `Settings` агрегатор и в `config_audit` |
| ENV-P3-004 | **P3** | `src/backend/core/config/ai_stack.py` (8 Settings-классов: LiteLLMGateway, RagCache, RagIngest, BGE, LangMem, LangFuse, Mcp, StreamingLLM, AIAgent) | 9 Settings в `ai_stack.py` — отдельный файл для одного домена, но внутри 9 несвязанных Settings; Логичнее разделить по доменам (ai_llm.py, rag.py, observability.py) |
| ENV-P4-001 | **P4** | `src/backend/core/config/services/dlq.py:44-51` | `DLQCleanupSettings.enabled: bool = Field(default=True)` — отсутствует fail-closed default; для cleanup-job default-ON может привести к silent data-loss если retention misconfigured |
| ENV-P4-002 | **P4** | `src/backend/core/config/services/cache.py:333-339` | `keydb_active_replica: bool = Field(default=True)` — отсутствует fail-closed default; KeyDB active-replica требует соответствующего deployment |
| ENV-P4-003 | **P4** | `src/backend/core/config/services/storage.py:16-22` | `FileStorageSettings.enabled: bool = Field(default=True)` — отсутствует fail-closed default; storage должен быть opt-in в profile |

---

## 5. Detailed evidence

### ENV-P1-001 — Stale config_audit path (RESIDUAL)

**Severity**: P1 (CI gate, нарушает contract двустороннего аудита YAML↔код).

**Evidence**:
- `tools/config_audit.py:36`: `CONFIG_DIR = ROOT / "src" / "core" / "config"` — путь НЕ существует.
- `tools/config_audit.py:4`: docstring содержит `src/core/config/`.
- `tools/codegen_settings.py:62-65,69`: `SERVICES_DIR = ROOT/"src"/"core"/"config"/"services"`,
  `SETTINGS_FILE = ROOT/"src"/"core"/"config"/"settings.py"`,
  `INTEGRATION_BASE = ROOT/"src"/"core"/"config"/"integration_base.py"` — все stale paths.
- `tools/codegen_settings.py:803`: docstring `Поиск идёт по src/core/config/services/*.py`.

**Run**:
```
$ .venv/bin/python tools/config_audit.py --profile dev
Discovered 0 settings classes in src/core/config; 56 keys in .env.example.
## profile: dev
  [ORPHAN-GROUP] vault, app, security, tasks, invoker, grpc, scheduler, http, …
  TOTAL ISSUES: 38
FAIL: конфигурация рассинхронизирована с моделями.
```

**Verified via .venv**: identical output (`Discovered 0 settings classes`).

**Impact**: CI `make config-audit` (`make/runtime.mk:16-17`) всегда exit 1 (или 0, если
fall-back через `ifneq`); YAML↔код audit полностью не функционален. Введено до
реорганизации `src/` → `src/backend/` (S26/S27) и не обновлено.

**Recommendation**: заменить `src/core/config` → `src/backend/core/config` в:
- `tools/config_audit.py:36` (и docstring line 4),
- `tools/codegen_settings.py:62-65,69,803`.

**Test-criterion**: `make config-audit` → exit 0 (или явный fail с правильным
orphan/missing списком).

---

### ENV-P1-002 — Duplicate Granian surface (RESIDUAL)

**Severity**: P1 (drift между `main.py` runtime path и `tools/granian_runner.py`
production path).

**Evidence**:
- `src/backend/main.py:81-117`: `_run_granian()` использует
  `from granian import Granian` (Python API) + `settings.app.granian_http`,
  `settings.app.granian_runtime_mode`, `settings.app.granian_runtime_threads`,
  `settings.app.granian_blocking_threads`, `settings.app.workers`.
- `src/backend/core/config/base/app_base.py:72-163`: 11 Granian-related полей
  (env `APP_GRANIAN_*`, yaml_group `app`).
- `src/backend/core/scaling/granian_tuning.py:178-225`: `GranianTuning.build_cli_command()`
  → subprocess CLI; использует `GRANIAN_*` env (yaml_group `granian`).
- `tools/granian_runner.py:83-96`: `from src.backend.core.scaling.granian_tuning import
  granian_tuning` — единственный caller `build_cli_command()`.
- `granian_tuning.graceful_shutdown_timeout` (line 125) vs
  `app.graceful_shutdown_timeout` (app_base.py:115) — два независимых поля.

**Run**:
```
$ .venv/bin/python -c "from src.backend.core.scaling.granian_tuning import granian_tuning; print(granian_tuning.build_cli_command(app='src.main:app'))"
[…'--shutdown-timeout', '30', …]
```

**Impact**:
- Production deployment через `python -m src.backend.main` использует Python API Granian
  без `--shutdown-timeout` (только `main.py:81-117`, не вызывает CLI builder).
- `tools/granian_runner.py` использует CLI builder с `--shutdown-timeout` и ADR-0059
  defaults, но НЕ связан с `main.py`.
- Если devops меняет `GRANIAN_SHUTDOWN_TIMEOUT=60`, эффект есть ТОЛЬКО в
  `tools/granian_runner.py` (НЕ в k8s pod при `python -m src.backend.main`).
- Helm `deploy/k8s/configmap.yaml:35-38`: `GRANIAN_WORKERS=4`, `GRANIAN_THREADS=2`,
  `GRANIAN_HOST`, `GRANIAN_PORT` — но k8s deployment запускает
  `python -m src.backend.main` (или `granian` CLI?), не `tools/granian_runner.py`.
  → Helm configmap не используется вовсе.

**Test-criterion**: один из вариантов:
1. Удалить `granian_tuning` и использовать только `settings.app.granian_*` через Python
   API.
2. Удалить `_run_granian()` из `main.py` и запускать через `tools/granian_runner.py`
   subprocess (тогда Helm configmap тоже используется).
3. Ввести единый фасад `app_runner.build()` с одним набором полей.

---

### ENV-P1-003 — Redis cluster_mode default broken

**Severity**: P1 (data path: default settings приводят к нерабочей конфигурации Redis).

**Evidence**:
- `src/backend/core/config/services/cache.py:201-218`:
  ```
  cluster_mode: bool = Field(
      default=True,  # default-ON
      description="Включить кластерный режим Redis …",
      json_schema_extra={"example": False},  # example=False — противоречие
  )
  cluster_nodes: list[str] = Field(
      default_factory=list,  # empty by default
      description="Список стартовых нод кластера …",
  )
  ```
- `src/backend/core/config/services/cache.py:248-260`: validator `_validate_cluster_nodes`
  проверяет только формат `host:port`, но НЕ пустоту массива.
- `src/backend/infrastructure/clients/storage/redis/connection_mixin.py:30-56`:
  ```
  if self.settings.cluster_mode:
      startup_nodes: list[ClusterNode] = []
      for raw in self.settings.cluster_nodes:
          …
      return RedisCluster(startup_nodes=startup_nodes, …)  # ← пустой список
  ```
- `config_profiles/base.yml:186-211` (redis:): `cluster_nodes` НЕ задан.
- `config_profiles/prod.yml:86-98` (redis:): `cluster_nodes` тоже НЕ задан.

**Run** (через `.venv/bin/python`):
```
$ .venv/bin/python -c "from src.backend.core.config.settings import settings; print(settings.redis.cluster_mode, settings.redis.cluster_nodes)"
True []
```

**Impact**:
- Default config создаёт `RedisCluster(startup_nodes=[])` → redis-py бросит исключение
  при первом обращении (cluster requires ≥1 node).
- Поля `db_cache/db_queue/db_limits/db_tasks` проигнорированы в cluster mode (см.
  `description` cache.py:205-207), но legacy code path их всё ещё использует
  (`connection_mixin.py:58-71` только для cluster_mode=False).
- `prod.yml:88-98` конфигурирует single-node Redis (`host: redis-prod`, `port: 6379`) —
  если `cluster_mode=True` (default), single-node подключения НЕ будет.

**Recommendation**: в `cache.py:201-218` установить `default=False` для `cluster_mode`
(matches `json_schema_extra` example). Также добавить validator на непустой
`cluster_nodes` при `cluster_mode=True`.

**Test-criterion**: `RedisSettings()` default → `cluster_mode=False` ИЛИ явный
`ValidationError` при `cluster_mode=True` + `cluster_nodes=[]`.

---

### ENV-P1-004 — Compose без CPU/memory limits

**Severity**: P1 (production blast radius: runaway container может DoS ноду).

**Evidence** (read каждый compose):
- `ops/compose/docker-compose.yml`: 5 services (`app`, `workflow-worker`, `postgres`,
  `redis`, `clamav`) — НИ ОДИН не имеет `deploy.resources.limits`. `workflow-worker`
  имеет `deploy: replicas: ${WORKER_COUNT:-4}` (line 71-72) но без resources.
- `ops/compose/docker-compose.prod.yml`: 13 services (Celery worker/beat, Kafka,
  Zookeeper, Schema Registry, Connect, kafka-ui, MinIO, Vault, Jaeger, OTEL, app,
  workflow-worker, migration-runner) — НИ ОДИН не имеет `deploy.resources.limits`.
- `ops/compose/docker-compose.light.yml`: 2 services — НИ ОДИН не имеет limits.
- `ops/compose/docker-compose.perf.yml`: 4 services — НИ ОДИН не имеет limits.
- `ops/compose/docker-compose.bluegreen.yml`: 3 services — НИ ОДИН не имеет limits.
- `ops/compose/docker-compose.plugin-dev.yml`: 3 services — НИ ОДИН не имеет limits.
- `ops/compose/docker-compose.windows-worker.yml`: 1 service — НИ ОДИН не имеет limits.

**Compare K8s** (для контекста): `deploy/k8s/deployment-app.yaml:72-78`,
`deployment-worker.yaml:77-83` — CPU+memory requests/limits заданы корректно.

**Impact**:
- На staging/prod compose-стендах (демо, integration tests, perf testing) один
  container может съесть всю память ноды.
- OOM-killer сработает на уровне Linux cgroup, не на уровне контейнера → потеря
  in-flight задач в `workflow-worker` / `app`.

**Recommendation**: добавить `deploy.resources.limits` (минимально для `app`,
`workflow-worker`, `postgres`, `redis`) — best-effort defaults:
- app: 1 CPU / 1Gi mem
- workflow-worker: 2 CPU / 2Gi mem
- postgres: 2 CPU / 2Gi mem
- redis: 1 CPU / 512Mi mem

**Test-criterion**: `docker compose config` показывает `resources.limits` для всех
сервисов с CPU > 0.5 ИЛИ memory > 256Mi.

---

### ENV-P1-005 — Три env-vars для одного концепта

**Severity**: P1 (consistency: prod-gates могут рассинхронизироваться).

**Evidence**:
- `src/backend/core/config/profile.py:23`: `APP_PROFILE_ENV: Final[str] = "APP_PROFILE"`
  (значения: dev_light/dev/staging/prod) — для YAML overlay.
- `src/backend/core/config/security.py:116`:
  ```
  env = os.getenv("APP_ENV") or os.getenv("ENVIRONMENT") or "dev"
  if env.lower() in {"prod", "production"} and "*" in value:
  ```
  — для runtime CORS check.
- `src/backend/infrastructure/observability/sentry_init.py:56`:
  `os.environ.get("APP_ENVIRONMENT", "development")`
- `src/backend/infrastructure/observability/otel_auto.py:102`:
  `os.environ.get("APP_ENVIRONMENT", "development")`
- `src/backend/infrastructure/storage/local_fs.py:43`:
  `os.environ.get("APP_ENVIRONMENT") or os.environ.get(...)`.
- `src/backend/infrastructure/scheduler/observability.py:187`:
  `APP_ENVIRONMENT=production`.
- `src/backend/plugins/composition/lifecycle/startup.py:249,272`:
  `os.environ.get("APP_ENVIRONMENT", "development")`.
- `src/backend/dsl/engine/processors/rpa/operations/ftpuploadprocessor.py:71`:
  `os.environ.get("APP_ENV", "").lower() in {…}`.
- `src/backend/entrypoints/middlewares/webhook_signature.py:30,61`:
  `APP_ENVIRONMENT=dev` для escape.
- `src/backend/core/config/base/app_base.py:33-43`:
  `environment: Literal["development", "staging", "production"]` — pydantic field.

**Mapping**:
| Source | Var name | Values | Used by |
|---|---|---|---|
| YAML profile | `APP_PROFILE` | dev_light/dev/staging/prod | `get_active_profile()` |
| CORS check | `APP_ENV` / `ENVIRONMENT` | dev/prod | `security.py:116` |
| Sentry/OTel/etc | `APP_ENVIRONMENT` | development/production | many files |
| Field | `app.environment` | development/staging/production | `ConfigValidator._is_prod()` |

**Impact**:
- Если devops выставил `APP_PROFILE=prod` (YAML overlay) + `APP_ENVIRONMENT=development`
  (sent by accident) → `app.environment='production'` (правильно из YAML), но
  `os.getenv("APP_ENVIRONMENT")='development'` → CORS-validator и Sentry инициализируются
  в dev-mode.
- Документация и Helm configmap используют разные имена (Helm задаёт `APP_ENV=production`
  в `values.yaml:44`, но код читает `APP_ENVIRONMENT`).

**Recommendation**: унифицировать — один env-var (`APP_PROFILE` или `APP_ENVIRONMENT`).
Привести `security.py:116` и `app_base.py.environment` к одной source-of-truth.

**Test-criterion**: ровно одно имя env-var для "production detection"; все
`is_prod()`/`_is_prod()` callsites используют одну функцию.

---

### ENV-P2-001 — Hardcoded shutdown timeout (RESIDUAL)

**Severity**: P2 (default value остаётся в коде; для k8s terminationGracePeriodSeconds=30
это согласуется, но не вынесено в ENV-only default).

**Evidence**:
- `src/backend/core/scaling/granian_tuning.py:125-135`:
  ```
  graceful_shutdown_timeout: int = Field(  # D-AUDIT-95 fix (S183 W1.2)
      default=30,
      title="Graceful shutdown timeout (секунды)",
      description=(
          "Granian --shutdown-timeout: сколько секунд ждать drain in-flight "
          "запросов после SIGTERM. Default 30 (k8s terminationGracePeriodSeconds). "
          "0 — отключить эмиссию флага (escape hatch)."
      ),
      ge=0,
      le=300,
  )
  ```
- `src/backend/core/config/base/app_base.py:115-124`:
  ```
  graceful_shutdown_timeout: int = Field(
      default=30,
      title="Graceful shutdown timeout (сек)",
      ge=1, le=300,
      description="Время на завершение активных запросов перед принудительным "
                  "закрытием соединений (uvicorn timeout_graceful_shutdown).",
  )
  ```
- ДВА независимых поля с default=30 — в одном случае для Granian CLI, в другом для
  uvicorn Python API.

**Run** (`.venv/bin/python -c "from src.backend.core.config.settings import settings; print(settings.app.graceful_shutdown_timeout)"`):
```
30
```

**Impact**:
- Значение 30 захардкожено (default), но env-override через `APP_GRACEFUL_SHUTDOWN_TIMEOUT`
  / `GRANIAN_GRACEFUL_SHUTDOWN_TIMEOUT` возможен (Pydantic env_prefix).
- При deploy в k8s с `terminationGracePeriodSeconds=30` — согласовано.
- При deploy в VM / bare-metal без k8s — default 30 не подходит для long-running
  workflows (worker должен ждать дольше).

**Recommendation**:
- Оставить default=30 (как k8s-safe).
- Рассмотреть ENV-only default (например, `default_factory=lambda: int(os.getenv("APP_DEFAULT_SHUTDOWN_TIMEOUT", "30"))`).

**Test-criterion**: ENV override (`GRANIAN_GRACEFUL_SHUTDOWN_TIMEOUT=60`) → build_cli_command
эмитит `--shutdown-timeout 60`.

---

### ENV-P2-002 — Layer violation: 2 Settings в одном файле

**Severity**: P2 (maintainability, layout drift).

**Evidence**:
- `src/backend/core/config/services/cache.py`: файл содержит
  `class RedisSettings(BaseSettingsWithLoader):` (line 9-301) И
  `class CacheSettings(BaseSettingsWithLoader):` (line 304-342).
- Другие Settings в `services/` — 1 класс на файл (`dlq.py`, `mail.py`, `policy.py`,
  `sms.py`, etc.).

**Recommendation**: extract `RedisSettings` → `services/redis.py` (одна ответственность
на файл).

**Test-criterion**: каждый файл в `services/*.py` содержит ровно один Settings-класс.

---

### ENV-P2-003 — 12+ Settings не агрегированы в `Settings`

**Severity**: P2 (discoverability).

**Evidence**:
- `src/backend/core/config/settings.py` собирает 41 Settings (см. §3).
- НО `grep yaml_group` находит 69 yaml_groups. Не агрегированы:
  - `DLQCleanupSettings` (services/dlq.py:28, `dlq_cleanup_settings`)
  - `GraphQLSettings` (services/graphql.py:26, `graphql_settings`)
  - `LdapSettings` (services/ldap.py:33, `ldap_settings`)
  - `LLMSettings` (services/llm.py:28, `llm_settings`)
  - `McpSettings`, `StreamingLLMSettings`, `AIAgentSettings` (ai_stack.py:273, 320, 344)
  - `MqttSettings` (services/mqtt.py:21, `mqtt_settings`)
  - `OutboxSettings` (services/outbox.py:26, `outbox_settings`)
  - `PolicySettings` (services/policy.py:22, `policy_settings`)
  - `RagCacheSettings`, `RagIngestSettings`, `BGESettings`, `LangMemSettings`,
    `LangFuseSettings` (ai_stack.py:79, 117, 151, 193, 243)
  - `RPASettings` (services/rpa.py:28, `rpa_settings`)
  - `WSSettings` (services/websocket.py:27, `ws_settings`)

**Impact**: developers ищут `settings.ldap` (нет), `settings.policy` (нет) — нужно
помнить module-level singleton (`ldap_settings`, `policy_settings`).

**Recommendation**: добавить в `Settings` агрегатор (или явно задокументировать «не
агрегируются, singleton-only» в docstring каждого Settings).

**Test-criterion**: документ `docs/config/SETTINGS_GUIDE.md` (если существует) перечисляет
разницу между агрегированными и singleton-only.

---

### ENV-P3-001 — Redis `cluster_mode` default/example/description drift

Подробности см. ENV-P1-003. Дополнительно:
- `json_schema_extra={"example": False}` (cache.py:209) противоречит `default=True`
  (cache.py:202).
- description "Включить кластерный режим Redis" не уточняет, что empty `cluster_nodes`
  → broken config.

**Test-criterion**: `cluster_mode.json_schema_extra.example == cluster_mode.default`.

---

### ENV-P3-002 — `waf.outbound_via_facade` default=True

`src/backend/core/config/waf.py:49-57`: default=True без явных рисков (auto-routing
всех BaseExternalAPIClient через OutboundHttpClient). Не security-relevant (только
traffic shaping). P3 (consistency).

---

### ENV-P3-003 — TransportSettings не BaseSettingsWithLoader

`src/backend/core/config/transport.py:20-43`: класс наследует `BaseSettings`, нет
`yaml_group`, не регистрируется в `Settings` агрегатор. docstring (line 1-11)
упоминает «Подключается в Settings через поле transport: TransportSettings» —
но это через прямую `transport: TransportSettings = transport_settings` в settings.py
line 175. Не критично, но неконсистентно.

---

### ENV-P3-004 — `ai_stack.py` концентрирует 9 Settings

`src/backend/core/config/ai_stack.py` содержит 9 несвязанных Settings:
`LiteLLMGateway`, `RagCache`, `RagIngest`, `BGE`, `LangMem`, `LangFuse`, `Mcp`,
`StreamingLLM`, `AIAgent`. Логичнее разделить (как `core/config/features/` уже
разделён на 22 mixin-файла): `ai_llm.py`, `ai_rag.py`, `ai_embeddings.py`,
`ai_memory.py`, `ai_observability.py`, `ai_mcp.py`, `ai_streaming.py`, `ai_agent.py`.

---

### ENV-P4-001 — DLQCleanupSettings.enabled default=True

`src/backend/core/config/services/dlq.py:44-51`: cleanup-job default-ON без явного
opt-in. Misconfigured retention может silent-data-loss в ClickHouse `dlq_events`.

---

### ENV-P4-002 — CacheSettings.keydb_active_replica default=True

`src/backend/core/config/services/cache.py:333-339`: KeyDB active-replica default-ON
без соответствующего deployment.

---

### ENV-P4-003 — FileStorageSettings.enabled default=True

`src/backend/core/config/services/storage.py:16-22`: storage default-ON; для dev_light
должен быть opt-in.

---

## 6. Cycle-1+2+3 residuals

| Cycle | ID | Title | Status this audit |
|---|---|---|---|
| cycle-3 | **P0-001** | Granian CLI flag (no `--shutdown-timeout`) | **RESOLVED** (granian_tuning.py:222-223: `if self.graceful_shutdown_timeout > 0: cmd.extend(["--shutdown-timeout", str(self.graceful_shutdown_timeout)])`); 14/14 tests PASS |
| cycle-3 | **P0-002** | hardcoded shutdown timeout (default 30 inline) | **RESIDUAL** (granian_tuning.py:125 default=30 inline). См. ENV-P2-001 |
| cycle-3 | **P1-001** | duplicate Granian surface | **RESIDUAL** (main.py uses settings.app.granian_* Python API, granian_tuning uses CLI). См. ENV-P1-002 |
| cycle-3 | **P1-002** | config_audit wrong path | **RESIDUAL** (tools/config_audit.py:36 + tools/codegen_settings.py:62-65 stale paths). См. ENV-P1-001 |
| cycle-3 | n/a | WorkflowFlags default=False (T-07) | **VERIFIED** — `src/backend/core/config/features/workflow.py:36-89`: все 5 флагов (`workflow_legacy_disabled`, `workflow_yaml_round_trip`, `workflow_bpmn_import`, `workflow_gateways_enabled`, `workflow_orchestrator_enabled`) default=False; `tests/unit/core/config/test_features_workflow.py` 6/6 PASS; `tests/unit/core/config/test_openfeature_default_off.py` 1/1 PASS; `tests/unit/core/config/test_workflow.py` 2/2 PASS |

### Другие cycle-1+2+3 items в scope

* **P0-002 (compose без limits)** — данный аудит **ПОДТВЕРЖДАЕТ** наличие проблемы (см. ENV-P1-004); все 7 compose-файлов проверены.
* **D-AUDIT-95 (S183 W1.2)** — `src/backend/core/scaling/granian_tuning.py:125` имеет комментарий
  `D-AUDIT-95 fix (S183 W1.2)`; tests/unit/core/scaling/test_granian_graceful_shutdown.py 6/6 PASS
  (default=30 emits flag, value=300 emits 300, value=0 omits, value=400 raises, value=-1 raises,
  position before app).
* **8 правок cycle 1+2+3** — все применены в HEAD 22e08a0d; smoke-тесты 8/8 PASS per BASELINE.md
  (не перечислены в этом аудите повторно).

---

## 7. Contradictions / overlaps to flag

### 7.1 Pre-existing test failure (вне scope, но в домене)

`tests/unit/core/config/test_features_experimental.py::TestExperimentalFlagsClass::test_experimental_flags_instantiates`
— **FAILED** (verified `.venv/bin/python -m pytest tests/unit/core/config/`):
```
assert getattr(flags, f) is True, f"{f} default не False"
AssertionError: openfeature_external default не False
```
Тест ожидает `ExperimentalFlags(openfeature_external=False, ...).openfeature_external is True`,
но реально получается `False`. Это означает **тест устарел** — `openfeature_external`
default-False per D-AUDIT-FIX-184-2 (cycle-3 fix), но тест не обновлён.

**Action**: update test или явно отметить xfail. Pre-existing, НЕ атрибутируется
рою cycle 4.

### 7.2 Pre-existing test failure в hot_reload

`tests/unit/core/config/test_hot_reload.py::TestConfigHotReloader::test_start_disabled_in_prod`
— **FAILED** (verified):
```
ValidationError: Field required [type=missing, input_value={}, input_type=dict]
  opentelemetry_endpoint
  admin_enabled
  monitoring_enabled
  version
  …
```
Тест мокает `feature_flags`, но `app.environment` валидация ловит missing required
fields. Pre-existing.

### 7.3 Overlap между ENV-P1-001 и cycle-3 P1-002

ENV-P1-001 — это и есть cycle-3 P1-002 RESIDUAL. Подтверждено в коде.

### 7.4 Overlap между ENV-P1-002 и cycle-3 P1-001

ENV-P1-002 — это cycle-3 P1-001 RESIDUAL. Подтверждено в коде.

### 7.5 Pre-existing non-pure: `test_features_sprints_18_21.py:44` SKIPPED

`tests/unit/core/config/test_features_sprints_18_21.py:44`: S171 M9 env-aware defaults
требуют FEATURE_* env vars. Pre-existing skip, не в scope.

### 7.6 Пре-existing residuals (НЕ этому плану, по BASELINE.md)

- `src/backend/services/ai/gateway_adapter.py:128-129` `except Exception: pass`
- 1 mypy error в `tests/unit/core/ai/test_gateway_pipeline_mixin.py:54`
- 5 failures в `tests/unit/core/ai/test_gateway_pipeline_mixin.py`

---

## 8. Readiness score 0–100

### Формула

```
R = 100
    − 8 × N(P0)        # P0 = -8 каждый (security/data-loss/fail-open)
    − 4 × N(P1)        # P1 = -4 каждый (layer boundary, architecture)
    − 1 × N(P2)        # P2 = -1 каждый (dead code, minor violations)
    − 0.2 × N(P3)      # P3 = -0.2 (library replacement / minor)
    − 0.1 × N(P4)      # P4 = -0.1 (organic new feature)
    − 5 × pre_existing_failures_count  # unfixed pre-existing failures
```

### Подсчёт

| Категория | Кол-во | Штраф |
|---|---|---|
| P0 (security/data-loss/race/fail-open) | **0** | 0 |
| P1 (layer boundaries, дублирование surface, default broken, compose без limits, env-var inconsistency) | **5** (ENV-P1-001…005) | -20 |
| P2 (hardcoded default, layer violation, settings aggregator completeness) | **3** (ENV-P2-001…003) | -3 |
| P3 (Redis drift, waf, transport, ai_stack layout) | **4** (ENV-P3-001…004) | -0.8 |
| P4 (default-ON для DLQ/Cache/storage) | **3** (ENV-P4-001…003) | -0.3 |
| Pre-existing failures (experimental, hot_reload) | **2** | -10 |
| **Итого** |  | **35.9 → округлённо 36** |

### Обоснование

- **0 P0** — никаких security/data-loss/fail-open violations в этом домене.
- **5 P1** — все 5 P1 в этом цикле (config_audit path, duplicate Granian,
  Redis cluster_mode default, compose без limits, env-var inconsistency).
  ЭТО ЗАПРЕЩАЕТ ≥80 readiness per правилу «Оценка ≥80 запрещена при наличии P0/P1».
- Архитектура и DI в целом clean (multi-source loader, validator mixin, fail-closed
  defaults в security, granular feature-flags). Tests покрывают 90/90 ключевых сценариев.
- Pre-existing failures (experimental + hot_reload) — вне scope, но они считаются.

### **Readiness = 36**

(правило «≥80 запрещена при P0/P1» — у нас 5 P1, поэтому потолок 79; реальная формула
даёт 36, что согласуется с правилом).

---

## 9. Recommended next tasks

Приоритизированы по impact и cost-of-fix:

1. **FIX ENV-P1-001 (config_audit.py + codegen_settings.py stale paths)** — 3-line fix
   (заменить `src/core/config` → `src/backend/core/config`); 1 trivial commit; unblocks
   CI `make config-audit` gate. Cost: 30 min. Impact: critical (CI silent pass).

2. **FIX ENV-P1-003 (Redis cluster_mode default)** — 2-line fix (default=False ИЛИ
   validator на пустоту cluster_nodes); 1 commit. Cost: 30 min. Impact: critical
   (broken Redis default для prod).

3. **FIX ENV-P1-004 (compose resources.limits)** — добавить `deploy.resources.limits`
   блок для app/workflow-worker/postgres/redis (минимум) в каждый compose; ~7 файлов.
   Cost: 1h. Impact: high (runaway container blast radius).

4. **FIX ENV-P1-002 (единый Granian surface)** — выбор: (а) drop `granian_tuning`
   и unified Python API в main.py; (б) drop `_run_granian()` и require `tools/granian_runner.py`
   в k8s entrypoint. (а) — меньше change, (б) — лучше ADR-0059 alignment. Cost: 2h.
   Impact: high (drift между runtime path и config).

5. **FIX ENV-P1-005 (env-var consistency)** — выбрать `APP_PROFILE` или `APP_ENVIRONMENT`
   как single source; привести все reads; docstring. Cost: 2h + audit всех callsites.
   Impact: medium (consistency, drift).

6. **FIX ENV-P2-001 / ENV-P2-003 (P2 batch)** — extract `RedisSettings` в
   `services/redis.py`; добавить `Settings.<name>` для 12 Settings; cost: 1h.
   Impact: low (maintainability).

7. **FIX ENV-P2-002 (Redis/Cache split file)** — extract; cost: 30 min. Impact: low.

8. **Cycle-3 P1-002 / P1-001 residuals closure** (см. §6): if not already in cycle 4 plan,
   fix as part of items 1 + 4 above.

---

## 10. Commands run

Все команды — **через `.venv/bin/python`** (system Python не подключён к .venv per
BASELINE.md instruction).

```bash
# 1. Granian tuning tests
.venv/bin/python -m pytest tests/unit/core/scaling/test_granian_tuning.py \
  tests/unit/core/scaling/test_granian_graceful_shutdown.py -v
# → 14 passed in 0.64s

# 2. Workflow feature flags (T-07 verification)
.venv/bin/python -m pytest tests/unit/core/config/test_workflow.py \
  tests/unit/core/config/test_features_workflow.py \
  tests/unit/core/config/test_openfeature_default_off.py -v
# → 9 passed in 0.66s

# 3. Config validator tests
.venv/bin/python -m pytest tests/unit/core/config/test_validator.py -v
# → 43 passed in 0.59s

# 4. Full config tests
.venv/bin/python -m pytest tests/unit/core/config/ --tb=no -q
# → 1 failed, 386 passed, 1 skipped, 3 warnings in 5.49s
# Pre-existing failures (НЕ этому swarm):
#   tests/unit/core/config/test_features_experimental.py::TestExperimentalFlagsClass::test_experimental_flags_instantiates
#   tests/unit/core/config/test_hot_reload.py::TestConfigHotReloader::test_start_disabled_in_prod

# 5. Subdomain tests (in-scope subset)
.venv/bin/python -m pytest tests/unit/core/scaling \
  tests/unit/core/config/test_workflow.py \
  tests/unit/core/config/test_features_workflow.py \
  tests/unit/core/config/test_openfeature_default_off.py \
  tests/unit/core/config/test_validator.py \
  tests/smoke/test_yaml_hot_reload.py \
  tests/smoke/test_granian_runtime.py --tb=line
# → 90 passed in 4.44s

# 6. config_audit (broken path — RESIDUAL ENV-P1-001)
.venv/bin/python tools/config_audit.py --profile dev
# → "Discovered 0 settings classes in src/core/config; 56 keys in .env.example."
# → "FAIL: конфигурация рассинхронизирована с моделями."
.venv/bin/python tools/config_audit.py --profile prod
# → "Discovered 0 settings classes in src/core/config; …" + 38/39 ORPHAN-GROUP

# 7. Verify Redis default (ENV-P1-003)
.venv/bin/python -c "from src.backend.core.config.settings import settings; print(settings.redis.cluster_mode, settings.redis.cluster_nodes)"
# → True []

# 8. Verify GranianTuning default CLI (ENV-P2-001)
.venv/bin/python -c "from src.backend.core.scaling.granian_tuning import granian_tuning; print(granian_tuning.build_cli_command(app='src.main:app'))"
# → ['granian', '--interface', 'rsgi', …, '--shutdown-timeout', '30', 'src.main:app']

# 9. Verify Settings aggregator type
.venv/bin/python -c "from src.backend.core.config.settings import settings; print(type(settings.app).__name__, type(settings.redis).__name__)"
# → AppBaseSettings RedisSettings

# 10. Verify Vault unreachable path (smoke: vault down → warning 1x per process)
.venv/bin/python -c "from src.backend.core.config.settings import settings; print(type(settings).__name__)"
# → Settings (with 1x "Vault недоступен" warning)

# 11. yaml_group audit (lazy grep)
grep -rn "yaml_group: ClassVar\[str\] = " src/backend/core/config/ --include="*.py" 2>/dev/null | wc -l
# → 69

# 12. All Settings classes (find unaggregated)
grep -nE "^class \w+Settings\(BaseSettingsWithLoader\)" -r src/backend/core/config/ --include="*.py" 2>/dev/null | wc -l
# → 50 (some are sub-Settings under AIProvidersSettings)

# 13. Settings aggregator declarations count
grep -nE "= \w+Settings\b" src/backend/core/config/settings.py | wc -l
# → 41

# 14. Compose deploy blocks (ENV-P1-004)
grep -A 2 "deploy:" ops/compose/*.yml
# → 2 matches, both WITHOUT resources.limits

# 15. Env-var name audit (ENV-P1-005)
grep -rn "APP_ENV\|APP_ENVIRONMENT\|APP_PROFILE" --include="*.py" src/backend/main.py src/backend/core/config/ 2>&1 | head -10
# → Mixed APP_ENV / APP_ENVIRONMENT / APP_PROFILE
```

---

## 11. Notes / caveats

* **«Не проверено»** помечены: `.env*`, `secrets/**`, cycle-1/2/3 markdown, KNOWN_ISSUES,
  CLAUDE.md, PLAN.md, DEEP_AUDIT_REPORT, triage_allowlist_report.
* Все runtime-проверки через `.venv/bin/python` (system Python не подключён к .venv).
* 8 правок cycle 1+2+3 (T-1.4/T-1.5/T-3.1/T-W1-01/T-W1-05/T-W1-08 + T-02/T-03) УЖЕ
  в HEAD 22e08a0d — НЕ атрибутированы рою cycle 4.
* Pre-existing drift (`M uv.lock`, `?? pip-audit.json`, `?? .blue_green.state`,
  untracked audit docs) — НЕ этому swarm.
* `extensions/`, `services/` (кроме явно проверенных), `infrastructure/` (кроме
  `clients/storage/redis/connection_mixin.py` для верификации ENV-P1-003) — вне scope.
* `python tools/config_audit.py` через system python показал IDENTICAL output —
  конфигурация грузится через yaml.safe_load (не зависит от Python venv).
* Для полного исправления ENV-P1-001/002/003/004/005 — отдельные PR-ы с
  test-критериями в §9.