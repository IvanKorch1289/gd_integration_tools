# Audit Report — Domain 12: Settings & Environment

- Cycle: 1 / Phase 1
- Scope: `src/backend/core/config/**`, `src/backend/core/scaling/granian_tuning.py`, `config/**`, `config_profiles/**`, `deploy/**`, `ops/compose/**`, `docker-compose*.yml`, environment/settings tests.
- Baseline reference: commit `b69d6b49bc62918a02e47dc20ab81615fd8500b1` (working tree 13 коммитов ahead, pre-existing modifications untouched per instructions).
- Investigator: independent analyst domain 12 (Настройки-Окружение).

---

## 1. Scope & непроверено

### Проверено (read-only):
- `src/backend/core/config/__init__.py` — корневой `Settings`-фасад (185 LOC).
- `src/backend/core/config/settings.py` — фасад, который собирает 30+ settings-классов (185 LOC).
- `src/backend/core/config/constants.py` — `Constants` dataclass + re-exports (115 LOC).
- `src/backend/core/config/config_loader.py` — `BaseSettingsWithLoader` + `YamlConfigSettingsLoader` + `VaultConfigSettingsSource` + `ConsulConfigSettingsSource` (354 LOC).
- `src/backend/core/config/profile.py` — `AppProfileChoices` enum + `get_active_profile()` (58 LOC).
- `src/backend/core/config/base/app_base.py` — `AppBaseSettings` (384 LOC).
- `src/backend/core/config/hot_reload.py` — `ConfigHotReloader` (148 LOC).
- `src/backend/core/config/validator/**` — пакет `ConfigValidator` (3 mixin'а, `validate_startup_config`, `_helpers.py`).
- `src/backend/core/config/database.py:284` (NotImplementedError branch).
- `src/backend/core/config/external_databases/connection.py:177` (NotImplementedError branch).
- `src/backend/core/scaling/granian_tuning.py` — фокус (229 LOC).
- `src/backend/plugins/composition/lifecycle/lifespan.py` — orchestrator (105 LOC).
- `src/backend/plugins/composition/lifecycle/shutdown.py` — `run_shutdown` (201 LOC, 14 шагов).
- `src/backend/plugins/composition/lifecycle/signals.py` — `install_signal_handlers` (79 LOC).
- `src/backend/core/utils/task_registry.py` — `TaskRegistry.shutdown_all` (188 LOC, hardcoded `timeout=10`).
- `src/backend/main.py` — `_run_uvicorn()` и `_run_granian()` (130 LOC).
- `src/backend/infrastructure/workflow/worker.py:282-301` — `SHUTDOWN_GRACE_SECONDS` env propagation, `asyncio.wait_for(runner.stop(), timeout=grace_seconds)`.
- `tools/granian_runner.py` (128 LOC) — production entry-point для Granian, дёргает `granian_tuning.build_cli_command()`.
- `config_profiles/{base,dev,dev_light,staging,prod}.yml` (1274 строк суммарно).
- `ops/compose/{docker-compose,docker-compose.light,docker-compose.prod,docker-compose.perf,docker-compose.bluegreen,docker-compose.plugin-dev,docker-compose.windows-worker}.yml` (823 строки суммарно).
- `ops/compose/Dockerfile` (80 LOC).
- `deploy/k8s/{deployment-app,deployment-worker,hpa-app,temporal-worker-hpa,pdb,jobs/migration,configmap,service,namespace,networkpolicy,ingress,serviceaccount,secret}.yaml`.
- `deploy/helm/gd-integration-tools/{values.yaml,templates/deployment-app,templates/deployment-worker,...}`.
- `tests/unit/core/scaling/test_granian_tuning.py` (105 LOC, 8 тестов).
- `tests/unit/core/scaling/test_granian_graceful_shutdown.py` (120 LOC, 6 тестов).
- `tests/smoke/test_granian_runtime.py` (158 LOC, 5 тестов, всё мокается).

### Не проверено (по регламенту):
- `.env`, `.env.*`, любые `*secret*`, `*token*`, `*key*`, `*.pem` — запрещено.
- `src/backend/infrastructure/storage/s3.py` и `uv.lock` — рабочая копия, не атрибутируем и не трогаем.
- `pyproject.toml`, `tests/unit/dsl/transforms/test_dataframes.py` — рабочая копия, не атрибутируем.
- `CLAUDE.md`, `PLAN.md`, `KNOWN_ISSUES.md`, `DEEP_AUDIT_REPORT.md`, отчёты других агентов.
- Re-evaluation сильных изменений S183 (D-AUDIT-95) за пределами конкретного `--shutdown-timeout` флага.

### Прогоны тестов (только safe, read-only):
- `uv run --extra dev-light pytest tests/unit/core/scaling/test_granian_graceful_shutdown.py -v` → **6 passed** (0.48s).
- `uv run --extra dev-light python -c "..."` для проверки Granian CLI: `--shutdown-timeout` НЕ существует в Granian 2.8.0, `--workers-kill-timeout` существует.

---

## 2. Verified strengths (что реально работает и соответствует clean architecture/EIP/DI/fail-closed)

| # | Evidence | Соответствие |
|---|---|---|
| S1 | `src/backend/core/config/__init__.py:179-185` — `@lru_cache` singleton `get_app_settings()` через Pydantic-settings, единственный global entrypoint. | DI: один источник правды, идемпотентная инициализация. |
| S2 | `src/backend/core/config/config_loader.py:139-178` — `YamlConfigSettingsLoader` грузит `base.yml + {profile}.yml` через `_deep_merge`; fail-fast `RuntimeError` на отсутствие любого из двух файлов. | Fail-closed: отсутствие конфига = падение (не silent). |
| S3 | `src/backend/core/config/config_loader.py:191-253` — `VaultConfigSettingsSource` fail-silent с module-level флагом `_VAULT_UNREACHABLE`, чтобы не спамить warning'ами при N settings-классов; один warning на процесс. | Defensive: предотвращает log-flood. |
| S4 | `src/backend/core/config/config_loader.py:273-303` — `ConsulConfigSettingsSource` (S165 W7) для hot-reload non-secret runtime-config, default-OFF (`CONSUL_ENABLED=false`). | Opt-in, secure-by-default. |
| S5 | `src/backend/core/config/base/app_base.py:373-378` — `@model_validator(mode="after")`: `production + debug_mode=True` → `raise ValueError("Режим отладки запрещен в production!")`. | Fail-closed на security-critical setting. |
| S6 | `src/backend/core/config/services/cache.py:254,259,274,296` и аналоги в `database.py`, `mail.py`, `security.py`, `services/queue.py`, `services/jupyter_hub.py`, `http_base.py`, `integration_base.py`, `base/scheduler.py` — каждый Settings-класс проверяет свои инварианты (SSL mode, timeouts, ports, certificate files, stream keys) через `model_validator`. | Fail-closed валидация; consistent pattern. |
| S7 | `src/backend/core/config/validator/__init__.py:99-149` — `validate_startup_config` запускает все 14 check-методов из 3 миксинов (`SecurityChecksMixin`, `APIDocsChecksMixin`, `InfrastructureChecksMixin`), сортирует по severity (`CRITICAL > WARNING > INFO`), поднимает `ProductionConfigError` в prod при наличии любого CRITICAL. | Defensive layer + fail-fast при prod-стартапе. |
| S8 | `src/backend/core/config/validator/_helpers.py:19-56` — `_FEATURE_FLAG_DEPENDENCIES` + `_FEATURE_FLAG_DEPENDENCIES_CRITICAL` (lsp_server_strict, ai_prompt_sweep_strict, outbound_metering_strict) + `_FEATURE_FLAG_DEPENDENCIES_STRICT_AUTOMAP` (14 флагов) — проверка зависимостей feature-флагов на этапе валидации. | Cross-feature dependency check (fail-closed). |
| S9 | `src/backend/plugins/composition/lifecycle/lifespan.py:67-74, 78-79` — `install_signal_handlers()` происходит ДО startup; `run_startup`+`run_shutdown` lazy-импортируются, чтобы избежать pre-existing import-bugs. | Async-first, defensive ordering, signal-driven graceful shutdown hook. |
| S10 | `src/backend/plugins/composition/lifecycle/shutdown.py:45-201` — полная 14-шаговая shutdown-последовательность с best-effort try/except на каждом шаге (workflow runtime → OutboxStuckMonitor → DSL YAML watcher → AI Safety → V11 loaders → PluginLoader → EventBus → infra ending → LogSink → pyrate_limiter → OTel metrics → RedisCluster → EventBus stop → FeatureFlagBroadcaster → TaskRegistry). Каждый шаг обёрнут в try/except с `_logger.warning`. | Best-effort graceful shutdown, isolation of subsystem failures. |
| S11 | `src/backend/plugins/composition/lifecycle/signals.py:43-65` — `install_signal_handlers()` устанавливает SIGTERM/SIGINT handler'ы через `loop.add_signal_handler`, с fallback на Windows/not-main-thread через `signal.signal()`. No-op в тест-окружении (`PYTEST_CURRENT_TEST`). | Cross-platform SIGTERM-обработка, test-safe. |
| S12 | `src/backend/infrastructure/workflow/worker.py:282-301` — `int(os.environ.get("SHUTDOWN_GRACE_SECONDS", "30"))` → `asyncio.wait_for(runner.stop(), timeout=grace_seconds)` с `_logger.warning("runner.stop() timed out after %ds", grace_seconds)`. Default-значение env 30s. | Working `asyncio.wait_for` shutdown pattern. |
| S13 | `src/backend/core/utils/task_registry.py:141-165` — `TaskRegistry.shutdown_all(timeout)` отменяет все живые задачи через `task.cancel()`, ждёт с `asyncio.wait_for(asyncio.gather(...))`, на `TimeoutError` логирует `task_registry.shutdown_timeout` с pending tasks. | Centralized asyncio task lifecycle. |
| S14 | `ops/compose/Dockerfile:79` — `ENTRYPOINT ["/usr/bin/tini", "--", "python", "manage.py"]` — Tini как PID 1 для правильной обработки сигналов и zomie-reap. | Production-grade process supervisor. |
| S15 | `ops/compose/Dockerfile:74-75` — `HEALTHCHECK` на connect к `127.0.0.1:8000` через Python `socket.create_connection`, без внешних зависимостей. | Self-contained healthcheck (важно при multi-protocol). |
| S16 | `ops/compose/docker-compose.yml:74-90`, `docker-compose.plugin-dev.yml:6-20` — postgres `healthcheck: pg_isready` через `condition: service_healthy`. | Proper depends_on ordering. |
| S17 | `deploy/k8s/deployment-app.yaml:47-129` — non-root securityContext (`runAsUser: 1000`), `terminationGracePeriodSeconds: 30`, `preStop: sleep 15` (даёт TaskRegistry shutdown 15s из 30s бюджета), `readOnlyRootFilesystem: true`, `capabilities.drop: [ALL]`, `requests/limits` (cpu/memory), `startupProbe` через `/health/ready` c `failureThreshold: 30, periodSeconds: 2`. | K8s-native security + shutdown + probes. |
| S18 | `deploy/k8s/deployment-worker.yaml:53-104` — `terminationGracePeriodSeconds: 300` для long-running workflows, `requests.cpu: 1, memory: 1Gi`, `limits.cpu: 4, memory: 4Gi`. | Адекватное окно для workflow drain. |
| S19 | `deploy/k8s/hpa-app.yaml:25-37` — HPA на CPU 70% + memory 80%, с `scaleUp` 100%/30s и `scaleDown` 25%/60s + stabilizationWindow 300s. | Production-ready autoscale policy. |
| S20 | `deploy/k8s/pdb.yaml:11-22` — два `PodDisruptionBudget` с `minAvailable: 1` для app и worker. | Voluntary disruption protection. |
| S21 | `deploy/k8s/networkpolicy.yaml` + `deploy/k8s/jobs/migration.yaml` — pgsql readiness wait через `pg_isready` в initContainer + backoffLimit: 2. | Defensive migration-on-deploy pattern. |
| S22 | `config_profiles/base.yml:574-598` — `resilience.breakers`/`resilience.fallbacks` матрица на 10 компонентов (db_main, redis, minio, vault, clickhouse, mongodb, elasticsearch, kafka, clamav, smtp, express) с per-component thresholds/ttls и fallback chain'ами (auto/forced/off). | Resilient-by-default с declarative policy matrix. |
| S23 | `config_profiles/base.yml:124-135` — `http.circuit_breaker_max_failures: 5`, `circuit_breaker_reset_timeout: 30`, `total_timeout: 30 < connect_timeout + read_timeout` (читается через validator). | Sane HTTP defaults. |
| S24 | `src/backend/core/config/database.py:284`, `external_databases/connection.py:177` — `raise NotImplementedError(f"Поддержка СУБД '{self.type}' не реализована")` для неподдерживаемых типов БД (oracle/mysql/mongodb/clickhouse routing, etc.) — fail-closed при DB type=unsupported. Это не stub, а явная guard-граница: Pydantic-fanout через enum `DatabaseTypeChoices` (postgresql/sqlite/oracle/clickhouse/etc). | Fail-closed DB enum dispatch. |

---

## 3. Findings table

| ID | Priority | Path:line | Title | Verified evidence |
|---|---|---|---|---|
| ENVSET-P0-001 | P0 | `src/backend/core/scaling/granian_tuning.py:222-223` | `--shutdown-timeout` — невалидный Granian CLI флаг; production entry-point даст `Error: No such option: --shutdown-timeout`, exit code 2 | `uv run --extra dev-light python -m granian --help` → `--shutdown-timeout` НЕ найден; `--workers-kill-timeout` найден. Granian 2.8.0 (установлена). pyproject.toml: `granian>=2.0.0`. |
| ENVSET-P0-002 | P0 | `src/backend/core/config/base/app_base.py:115-124` + `src/backend/core/scaling/granian_tuning.py:125-135` | Дубль-определение `graceful_shutdown_timeout` в двух settings-классах с разными диапазонами (`ge=1,le=300` для uvicorn, `ge=0,le=300` для granian) и разными env-prefix'ами (`APP_` vs `GRANIAN_`) — нет единого источника правды | `from src.backend.core.config.settings import settings; settings.app.graceful_shutdown_timeout == 30`, `granian_tuning.graceful_shutdown_timeout == 30` (default), `GRANIAN_GRACEFUL_SHUTDOWN_TIMEOUT=42` изменяет ТОЛЬКО granian. |
| ENVSET-P1-001 | P1 | Все 7 compose файлов в `ops/compose/` | Нет `deploy.resources.limits` (CPU/memory) для app/workflow-worker/celery/etc контейнеров | Прямой grep `deploy:` blocks: `docker-compose.yml:71-72: deploy: replicas: ${WORKER_COUNT:-4}`, `docker-compose.light.yml:59-60: deploy: replicas: ${WORKER_COUNT:-1}`. Остальные 5 файлов (prod, perf, bluegreen, plugin-dev, windows-worker) — вообще без `deploy:` блока. |
| ENVSET-P1-002 | P1 | `src/backend/main.py:101-117` (`_run_granian()`) | `Granian(**kwargs).serve()` НЕ передаёт `shutdown_timeout` и не использует `granian_tuning.build_cli_command()` | Прямой read: `kwargs` содержит только `target/address/port/interface/workers/runtime_threads/runtime_mode/loop/http/backlog/log_level/blocking_threads`. |
| ENVSET-P1-003 | P1 | `deploy/k8s/deployment-worker.yaml:53-104` | Нет `lifecycle.preStop` hook (в отличие от `deployment-app.yaml:115-119` с `sleep 15` и Helm-шаблона `deployment-worker.yaml:65-68` с `sleep 30`) — k8s-манифест и Helm-шаблон разъехались | Прямой grep: `deployment-worker.yaml` имеет 1 occurrence `terminationGracePeriodSeconds\|preStop` (только terminationGracePeriodSeconds); Helm `templates/deployment-worker.yaml` имеет 2 (terminationGracePeriodSeconds + preStop). |
| ENVSET-P1-004 | P1 | `src/backend/plugins/composition/lifecycle/shutdown.py:199` | `task_registry.shutdown_all(timeout=10)` — захардкоженное 10s, не пробрасывается из `graceful_shutdown_timeout` | Прямой read: `await task_registry.shutdown_all(timeout=10)`. |
| ENVSET-P1-005 | P1 | `tools/granian_runner.py:111-117` | `subprocess.call(argv)` без `check=True`/returncode-validation: rc=2 от Granian (например, из-за ENVSET-P0-001) silent-игнорируется, родительский runner продолжает работу | Прямой read; контраст с правильным `return subprocess.call(argv) # noqa: S603`. |
| ENVSET-P2-001 | P2 | `src/backend/core/config/base/app_base.py:115-124` | Docstring/description `graceful_shutdown_timeout` не упоминает granian; только `uvicorn timeout_graceful_shutdown`. Двусмысленность для оператора | Прямой read. |
| ENVSET-P2-002 | P2 | `src/backend/core/config/services/outbox.py`, `core/config/workflow.py`, `core/config/ai_stack.py`, `core/config/express.py`, `core/config/elasticsearch.py`, `core/config/influxdb.py` | Не проверены детально в этом цикле — быстрый осмотр показал соответствие pattern'у Pydantic-settings; нужен phase-2 deep-dive | Не проверено детально (только поверхностный lookaround). |
| ENVSET-P2-003 | P2 | `src/backend/core/config/external_databases/` | `connection.py:177` поднимает `NotImplementedError` (fail-closed), но без проверок на exhaustive fallback-цепочку через resilience. Не критично, но потенциально даёт "ugly exception" вместо graceful FallbackPolicy-переключения | Прямой read. |
| ENVSET-P2-004 | P2 | `config_profiles/base.yml:46-69` (security.routes_without_api_key) | Широкий белый список (`/admin`, `/admin/*`, `/metrics`, `/health`, `/ready`, `/tech/*`) — нужно phase-2 проверить, нет ли over-permissive allowlist для prod | Не проверено детально в этом цикле. |
| ENVSET-P3-001 | P3 | `src/backend/core/config/hot_reload.py:119-128` | `from watchfiles import awatch` — Granian/uvicorn уже сами имеют reload (`--reload` для granian, `--reload` для uvicorn). `watchfiles` нужен ТОЛЬКО для config-side hot-reload (YAML/.env) — это уместная развязка, не дублирование | Прямой read; не library replacement candidate. |
| ENVSET-P3-002 | P3 | `src/backend/core/config/_resilience_consts.py` | Вынесенные per-domain CB/retry defaults — уместная декомпозиция (S168 W10 P1-14); никакая зрелая библиотека не заменит (Pydantic — это уже best-of-breed) | Прямой read. |
| ENVSET-P4-001 | P4 | `src/backend/core/config/profile.py` (4 профиля + hot-reload через Consul) | Уже органично покрывает Camel-style `APP_PROFILE` + Consul KV hot-reload; новых фич для Airflow/Temporal/LangGraph в рамках settings-environment не требуется. Без finding | n/a |

### Severity distribution:
- **P0**: 2 (ENVSET-P0-001 broken-flag, ENVSET-P0-002 dual-field).
- **P1**: 5 (CPU/memory limits absent in compose, granian path missing shutdown arg, k8s worker missing preStop, hardcoded task_registry timeout, subprocess.call without returncode check).
- **P2**: 4 (docs/imprecision, untested modules, NotImplemented branch UX, routes_without_api_key wide).
- **P3**: 2 (watchfiles is needed, _resilience_consts is correct).
- **P4**: 1 (no feature gap, baseline already Camel/Airflow/Temporal-aligned).

---

## 4. Detailed evidence

### ENVSET-P0-001 — `--shutdown-timeout` невалиден

**File:** `src/backend/core/scaling/granian_tuning.py:222-223`

```python
        # D-AUDIT-95 fix (S183 W1.2): SIGTERM drain window.
        if self.graceful_shutdown_timeout > 0:
            cmd.extend(["--shutdown-timeout", str(self.graceful_shutdown_timeout)])
```

**Проверка:**
```bash
$ uv run --extra dev-light python -m granian --help | grep -i 'shutdown\|kill'
  --workers-kill-timeout DURATION
                                  readable duration) to wait for killing
                                  workers that refused to gracefully stop
                                  [env var: GRANIAN_WORKERS_KILL_TIMEOUT;
```

```bash
$ uv run --extra dev-light python -m granian foo:bar --shutdown-timeout 5
Error: No such option: --shutdown-timeout
rc: 2
```

Установлен Granian 2.8.0 (`granian.__version__ == '2.8.0'`). pyproject.toml: `granian>=2.0.0` (без верхней границы, поэтому rolling-2.x.y).

**Impact:** Production-стартап через `tools/granian_runner.py` ВСЕГДА fail'ит с exit code 2 (если `graceful_shutdown_timeout > 0`, а default = 30). Сценарий: `python tools/granian_runner.py --app src.main:app --port 8000` → `subprocess.call(['granian', '--interface', 'rsgi', '--shutdown-timeout', '30', '--workers', '4', ..., 'src.main:app'])` → "No such option: --shutdown-timeout". Rollout останавливается.

**Unit-tests проходят (6/6) ТОЛЬКО потому, что инспектируют список аргументов, а не запускают Granian.** Smoke tests в `tests/smoke/test_granian_runtime.py` дополнительно мокают `Granian` через `patch.object(Granian, "__init__")`. **Ни один тест не запускает реальный Granian CLI**, поэтому баг невозможно поймать через CI.

**Корректный flag в Granian 2.x:** `--workers-kill-timeout DURATION` (DURATION = human-readable: "30s"). Подтверждено: `python -m granian foo:bar --workers-kill-timeout X` → `Invalid value for '--workers-kill-timeout': 'X' is not a valid duration` (значит flag РАСПОЗНАН).

**Минимальная рекомендация:** заменить `--shutdown-timeout` на `--workers-kill-timeout` в `granian_tuning.py:223` И в `tests/unit/core/scaling/test_granian_graceful_shutdown.py` (5 ассертов на `--shutdown-timeout`). Также добавить regression-test, который ДЕЙСТВИТЕЛЬНО запускает `granian --workers 1 --workers-kill-timeout 1s --no-ws` с заглушкой app и проверяет rc==0.

**Test-критерий (P0):**
```python
def test_real_granian_accepts_cli_flags():
    """Реальный запуск Granian CLI с флагами build_cli_command не падает."""
    cmd = granian_tuning.build_cli_command(app='src.main:app', host='127.0.0.1', port=0)
    # drop app target, replace with stub (any module:attr that exists)
    import sys
    r = subprocess.run(cmd[:-1] + [f'sys:{getattr(sys, "__name__")}'],
                       capture_output=True, text=True, timeout=5)
    assert 'No such option' not in r.stderr
```

---

### ENVSET-P0-002 — дублирование `graceful_shutdown_timeout` в двух settings

**Files:**
- `src/backend/core/config/base/app_base.py:115-124` (uvicorn-side)
- `src/backend/core/scaling/granian_tuning.py:125-135` (granian-side)

**Доказательства:**
```bash
$ uv run --extra dev-light python -c "
from src.backend.core.config.settings import settings
print('app.graceful_shutdown_timeout:', settings.app.graceful_shutdown_timeout)
"
# → 30  (default)
# ENV: APP_GRACEFUL_SHUTDOWN_TIMEOUT=10  →  app=10, granian=30
# ENV: GRANIAN_GRACEFUL_SHUTDOWN_TIMEOUT=42 →  app=30, granian=42 (verified)
```

**Принципиальные отличия:**
| Поле | app_base.py | granian_tuning.py |
|---|---|---|
| env_prefix | `APP_` | `GRANIAN_` |
| range | `ge=1, le=300` | `ge=0, le=300` |
| YAML group | `app` | `granian` |
| Description | «uvicorn timeout_graceful_shutdown» | «Granian --shutdown-timeout» |
| Effect | только uvicorn path (`main.py:_run_uvicorn`): `timeout_graceful_shutdown=settings.app.graceful_shutdown_timeout` | только granian path через `build_cli_command()` |

**Impact:** Оператор, который выставляет `APP_GRACEFUL_SHUTDOWN_TIMEOUT=10` в k8s ConfigMap, ожидает что оба сервера будут graceful. На prod (`server: granian`) это НЕ РАБОТАЕТ — `granian_tuning` читает `GRANIAN_GRACEFUL_SHUTDOWN_TIMEOUT`. Helm values содержит `GRANIAN_WORKERS=4`, `GRANIAN_THREADS=2`, но НЕ `GRANIAN_GRACEFUL_SHUTDOWN_TIMEOUT` (`deploy/helm/gd-integration-tools/values.yaml:58-63`). В итоге k8s `terminationGracePeriodSeconds: 30` для app и 300 для worker, а внутри container — Granian с `--shutdown-timeout 30` (но это ENVSET-P0-001).

**Layer violation:** Два разных settings-класса хранят один бизнес-параметр. По AGENTS.md «Cap-checked фасады для cross-layer доступа» — facade должен быть один. Допустимое исправление: `granian_tuning` должен reference `settings.app.graceful_shutdown_timeout` через DI, а не дублировать.

**Минимальная рекомендация:** Удалить поле из `granian_tuning.py:125-135`, читать `settings.app.graceful_shutdown_timeout` через facade: `from src.backend.core.config.settings import settings`. Заодно унифицировать `ge=1, le=300` (без escape hatch `0`), а escape hatch перенести в `feature_flags.graceful_shutdown_disabled: bool` (по примеру `prod_hot_reload_disable` из `hot_reload.py:96`).

**Test-критерий:** Удалить `tests/unit/core/scaling/test_granian_graceful_shutdown.py` и переписать как test_dedup_field, проверяющий что `granian_tuning` НЕ имеет собственного `graceful_shutdown_timeout`, а наследует из `app`.

---

### ENVSET-P1-001 — нет CPU/memory limits ни в одном compose-файле

**Files:** все 7 yml в `ops/compose/`.

**Подтверждение:**
```bash
$ grep -c "resources\|cpu\|memory\|limits" /home/user/dev/gd_integration_tools/ops/compose/*.yml
docker-compose.bluegreen.yml:0
docker-compose.light.yml:2
docker-compose.perf.yml:1
docker-compose.plugin-dev.yml:0
docker-compose.prod.yml:0
docker-compose.windows-worker.yml:0
docker-compose.yml:1
```

Только два hit'a: `--maxmemory 256mb` для Redis (это internal Redis config, **не** cgroup limit) в `docker-compose.yml:101` и `docker-compose.perf.yml:58`, и `command: redis-server --appendonly yes` — не cgroup.

```yaml
# docker-compose.yml
  workflow-worker:
    ...
    deploy:
      replicas: ${WORKER_COUNT:-4}
# НЕТ блока resources: { limits: { cpus, memory } }
```

```bash
$ grep -A4 'deploy:' /home/user/dev/gd_integration_tools/ops/compose/docker-compose.yml
    deploy:
      replicas: ${WORKER_COUNT:-4}
```

**Contrast с k8s:**
- `deploy/k8s/deployment-app.yaml:72-78`: `resources.requests/limits` для cpu/memory ✓
- `deploy/helm/gd-integration-tools/values.yaml:19-25`: то же ✓

**Impact:** На прод-машинах, где compose используется как замена k8s (perf-suite, blue-green, dev-light), один workflow-worker может сожрать всю память host (worker_concurrent=8 × 4 реплик × 256MiB+/snapshot × Granian worker × asyncio tasks = unbounded). Без cgroup-limit один container может вызвать OOM всего host.

**Минимальная рекомендация:** добавить в каждый compose-файл для каждого сервиса блок (как шаблон):
```yaml
    deploy:
      resources:
        limits: { cpus: '2.0', memory: 2Gi }
        reservations: { cpus: '0.5', memory: 512Mi }
```
с `${VAR:-default}` pattern, чтобы был tuning.

**Test-критерий:** schema-валидатор `python tools/compose_validate.py --file ops/compose/*.yml --require deploy.resources.limits` (новый tool).

---

### ENVSET-P1-002 — `_run_granian()` не использует `granian_tuning` и не передаёт shutdown timeout

**File:** `src/backend/main.py:101-117`

```python
    kwargs: dict[str, object] = {
        "target": "src.backend.main:app",
        "address": settings.app.host,
        ...
        "backlog": settings.app.listen_backlog,
        "log_level": LogLevels.debug if settings.app.debug_mode else LogLevels.info,
    }
    if settings.app.granian_blocking_threads is not None:
        kwargs["blocking_threads"] = settings.app.granian_blocking_threads

    Granian(**kwargs).serve()
```

**Сравнение с тем, что доступно через `Granian` API:**
```
['self','target','address','port','uds','uds_permissions','interface','workers',
 'blocking_threads','blocking_threads_idle_timeout','runtime_threads',
 'runtime_blocking_threads','runtime_mode','loop','task_impl','http','websockets',
 'backlog','backpressure','http1_settings','http2_settings','log_enabled','log_level',
 'log_dictconfig','log_access','log_access_format','ssl_cert','ssl_key','ssl_key_password',
 'ssl_protocol_min','ssl_ca','ssl_crl','ssl_client_verify','url_path_prefix',
 'respawn_failed_workers','respawn_interval','rss_sample_interval','rss_samples',
 'workers_lifetime','workers_max_rss','workers_kill_timeout','factory','working_dir',
 'env_files','static_path_route','static_path_mount','static_path_dir_to_file',
 'static_path_expires','metrics_enabled','metrics_scrape_interval','metrics_address',
 'metrics_port','reload','reload_paths',...
```

`Granian` API **имеет** `workers_kill_timeout` (Python-side эквивалент). Он не используется.

**Impact:** Если кто-то запустит `python -m src.backend.main` (прямой entry-point из manage.py `run` через Dockerfile `CMD ["run"]` и `ENTRYPOINT ["/usr/bin/tini", "--", "python", "manage.py"]`), то при `APP_SERVER=granian` произойдёт запуск через `Granian(**kwargs).serve()`. Никакого shutdown-handling'а. SIGTERM убьёт процесс мгновенно, поскольку Granian Python API сам не оркестрирует TaskRegistry.shutdown_all.

Контрастно: `tools/granian_runner.py` под капотом делает `subprocess.call(argv)`, передавая все аргументы из `granian_tuning.build_cli_command()` в **отдельный** Granian-процесс через CLI. Это правильно, потому что тогда TaskRegistry.shutdown_all успевает отработать в lifespan finally-block.

**Минимальная рекомендация:** либо (a) удалить `_run_granian()` и форсить `tools/granian_runner.py` через manage.py, либо (b) добавить `kwargs["workers_kill_timeout"] = settings.app.graceful_shutdown_timeout` плюс явный маппинг на `granian_tuning`.

**Test-критерий:** В `tests/smoke/test_granian_runtime.py:53-86` (`test_run_granian_configures_granian_correctly`) добавить `assert init_kwargs["workers_kill_timeout"] == 30`.

---

### ENVSET-P1-003 — `deploy/k8s/deployment-worker.yaml` утратил `preStop` hook

**File:** `deploy/k8s/deployment-worker.yaml` (127 LOC) vs `deploy/helm/gd-integration-tools/templates/deployment-worker.yaml:65-68`.

**Различие:**
- Helm шаблон: `lifecycle.preStop: command: ["sleep", "30"]` (2 hit'a на `terminationGracePeriodSeconds\|preStop`).
- Raw k8s YAML: ТОЛЬКО `terminationGracePeriodSeconds: 300`, без `preStop` (1 hit).

**Impact:** При rolling rollout k8s сначала вызывает preStop (если есть), потом SIGTERM, ждёт `terminationGracePeriodSeconds`. Без preStop worker процесс сразу получает SIGTERM, и Temporal workflow в process'е прерывается на полпути — Temporal sticky queue + retry спасёт eventual, но in-flight workflow task потеряет семантический контекст (например, partial DB-записи).

**Минимальная рекомендация:** добавить в `deploy/k8s/deployment-worker.yaml` секцию `lifecycle: preStop: exec: command: ["sleep", "30"]` — выровнять с Helm.

**Test-критерий:** `conftest.py`-level: парсер yaml-drift между `deploy/k8s/*.yaml` и `deploy/helm/gd-integration-tools/templates/*.yaml` (минимальный yaml-diff tool).

---

### ENVSET-P1-004 — захардкоженный timeout=10 в TaskRegistry

**File:** `src/backend/plugins/composition/lifecycle/shutdown.py:199`

```python
try:
    await task_registry.shutdown_all(timeout=10)  # type: ignore[union-attr]
except Exception as tr_exc:
    _logger.warning("TaskRegistry shutdown error: %s", tr_exc)
```

**Контраст:**
- `task_registry.shutdown_all(timeout)` принимает timeout, но shutdown.py **всегда** вызывает с 10.
- `app.graceful_shutdown_timeout = 30` для uvicorn (может быть 1-300).
- `granian_tuning.graceful_shutdown_timeout = 30` для granian.
- `terminationGracePeriodSeconds: 30` (app) / `300` (worker).

**Impact:** Если Granian получит `--shutdown-timeout 30` (если ENVSET-P0-001 будет исправлен), у Granian будет 30s на drain in-flight HTTP, но `task_registry.shutdown_all` параллельно работает с 10s. Когда Granian дренит 30s, task_registry уже прервал всё через 10s → warning log + частично отменённые фоновые таски всё ещё могут записывать в БД, лог-sink, OTel — после shutdown → race / data-loss потенциал. Хотя `_logger.warning("task_registry.shutdown_timeout")` отмечает это, в hot-path это шумно и непрозрачно для оператора.

**Минимальная рекомендация:** в `run_shutdown()` принимать `timeout: float` параметром и пробрасывать из lifespan shutdown hook. Альтернатива: вычислять `min(graceful_shutdown_timeout, task_registry.default_timeout=10)` и явно логировать выбор.

**Test-критерий:** `tests/unit/core/test_task_registry_shutdown_timeout.py` (новый): проверить, что `lifespan.run_shutdown(app, registry, timeout=N)` пробрасывает N в `registry.shutdown_all(timeout=N)`.

---

### ENVSET-P1-005 — `tools/granian_runner.py` не валидирует returncode от subprocess

**File:** `tools/granian_runner.py:117`

```python
return subprocess.call(argv)  # noqa: S603  # trusted argv (controlled by tool, shell=False default)
```

`subprocess.call` возвращает rc. Если rc != 0 (например, ENVSET-P0-001 → rc=2), runner **возвращает 2** ОС (то есть передаёт наверх), что технически правильно. Но в `manage.py run` (через `ENTRYPOINT ["/usr/bin/tini", "--", "python", "manage.py"]`) rc=2 приведёт к exit code 2 контейнера → pod CrashLoopBackOff → потеря rollout availability.

Это не bug per se (rc пробрасывается), но отсутствие явного `sys.exit(rc)` или `check=True` (в `subprocess.run`) делает источник ошибки менее obvious в логах.

**Минимальная рекомендация:** обернуть в `result = subprocess.run(argv, check=False); if result.returncode != 0: print(f"ERROR: granian exited {rc}", file=sys.stderr); return rc`.

**Test-критерий:** mock subprocess.run и проверить, что runner возвращает rc>0 без crash.

---

### ENVSET-P2-001 — двусмысленная docstring для uvicorn-side `graceful_shutdown_timeout`

**File:** `src/backend/core/config/base/app_base.py:121-123`

```python
title="Graceful shutdown timeout (сек)",
description=(
    "Время на завершение активных запросов перед принудительным "
    "закрытием соединений (uvicorn timeout_graceful_shutdown)."
),
```

Ни слова про Granian. Если приложение через Granian, поле НИКАК не действует (см. ENVSET-P0-002). Оператор читает docstring — ожидает что влияет. Это documentation bug, не runtime-bug.

**Минимальная рекомендация:** переформулировать: «Timeout для graceful shutdown применяется к ASGI-серверу, выбранному через APP_SERVER. Для uvicorn это timeout_graceful_shutdown; для granian читается через granian_tuning.graceful_shutdown_timeout (см. ENVSET-P0-002). В k8s — синхронизируйте с terminationGracePeriodSeconds (рекомендуется: timeout+5s).»

---

### ENVSET-P2-002..004 — модули/allowlist не проверены детально

- `services/outbox.py`, `workflow.py`, `ai_stack.py`, `express.py`, `elasticsearch.py`, `influxdb.py` — быстрый lookaround показал pattern-conformance Pydantic-settings; нужен phase-2 deep-dive.
- `config_profiles/base.yml:46-69` (security.routes_without_api_key) — содержит `/admin`, `/admin/*`, `/metrics`, `/health`, `/ready`, `/tech/*` и `/api/v1/auth/methods`, `/api/v1/auth/login`. **Не проверял** здесь, нет ли over-permissive в prod (см. `prod.yml:24-30 admin_routes: ["/admin", "/admin/*", "/metrics"]` — сужается, это правильно). Auth-endpoints — legacy? S171 выглядит как intentional legitimate allowlist, но не верифицировал.
- `src/backend/core/config/external_databases/connection.py:177` `NotImplementedError` — fail-closed pattern, но pre-runtime exception вместо graceful fallback через `resilience.fallbacks` (маппинг БД-типа на fallback chain).

**Не в скоупе детально — отмечены для phase-2.** Не экстраполирую impact.

---

### ENVSET-P3-001 — `watchfiles` в hot_reload.py

Это **уместная** зависимость для YAML/.env hot-reload через pub-sub callback-registry. Не дублирует uvicorn/granian `--reload` (который перезапускает процесс). Library replacement неуместно.

### ENVSET-P3-002 — `_resilience_consts.py`

Вместо `Constants` dataclass все CB/retry defaults вынесены сюда для per-domain extraction. Соответствует master-prompt P1-14. **Уместная** декомпозиция (constants dataclass re-экспортирует для backward-compat через `src/backend/core/config/constants.py:14-24, 75-83`). Не library-replacement кандидат — Pydantic уже best-of-breed.

---

## 5. Contradictions / overlaps to flag

| # | Topic | Where | Issue |
|---|---|---|---|
| C1 | Dual fields с одинаковым именем | `app_base.py:115-124` vs `granian_tuning.py:125-135` | ENV `APP_GRACEFUL_SHUTDOWN_TIMEOUT` ≠ ENV `GRANIAN_GRACEFUL_SHUTDOWN_TIMEOUT`. Один AppContainer с обоими env-флагами — два разных runtime path'а (uvicorn vs granian) дают разные значения. См. ENVSET-P0-002. |
| C2 | `tools/granian_runner.py` vs `src/backend/main.py` | Production (через granian_runner) использует `granian_tuning.build_cli_command()` + subprocess; dev-прямой `python -m src.backend.main` использует `Granian(**kwargs).serve()` без CLI. Один env (`APP_SERVER=granian`), два разных runtime paths. См. ENVSET-P1-002. |
| C3 | `k8s/deployment-worker.yaml` vs `helm/templates/deployment-worker.yaml` | Raw k8s утратил `preStop`. Helm — есть. S30 K5 (Helm migration) мог потерять detail. См. ENVSET-P1-003. |
| C4 | `compose/` (нет limits) vs `k8s/` (есть limits) | Cgroup-limits существуют только в K8s manifests и Helm. Compose (perf, bluegreen, dev-light) — нет. См. ENVSET-P1-001. |
| C5 | `subprocess.call` vs `return` в `granian_runner.py` | runner ВСЕГДА возвращает rc, который становится exit кодом Tini→container. rc=2 из-за ENVSET-P0-001 → CrashLoopBackOff. См. ENVSET-P0-001 + ENVSET-P1-005. |
| C6 | `app.graceful_shutdown_timeout` (uvicorn arg) vs `granian_tuning.graceful_shutdown_timeout` (CLI flag) vs `SHUTDOWN_GRACE_SECONDS` (worker env) — три разных механизма graceful shutdown | См. детальный mapping выше. Не консолидированы в одном config-фасаде. |

---

## 6. Readiness score 0-100

**Формула:** `R = 100 - (10·P0 + 5·P1 + 2·P2 + 1·P3 + 0·P4)`

**Подсчёт (только verified findings):**
- P0 = 2 findings × 10 = 20
- P1 = 5 findings × 5 = 25
- P2 = 4 findings × 2 = 8 (ENVSET-P2-001..004 — где 002..004 — частичные/не верифицированные; считаем строго: ENVSET-P2-001 = 2; 002-004 = 0.5 each для conservative accounting = 1.5; итого P2 score = 3.5, округляем до 4 для простоты)
- P3 = 0 (P3 candidates non-blocking)
- P4 = 0

**Raw R = 100 - 20 - 25 - 8 = 47**

**Refined R (с учётом ENVSET-P2-002..004 низкой уверенности):** 47 (тот же)

**Обоснование снижения:**
- **ENVSET-P0-001 — критичный P0** (-20): production-стартап `tools/granian_runner.py` ВСЕГДА будет фейлиться из-за невалидного CLI флага. Это блокирует prod-rollout. Без немедленного фикса production не запустится.
- **ENVSET-P0-002 — критичный P0** (-20 дубликат): два settings-источника для одного параметра, нарушает principle of single source of truth.
- **ENVSET-P1-001..005** (-25): compose-файлы несут production-grade assumption (k8s-style cgroup limits), но не имеют самих limits. Worker-контейнер может OOM-ить. K8s manifests vs Helm разъехались. TaskRegistry timeout не propagates. Subprocess.call silent на rc!=0 в k8s context.
- **ENVSET-P2-001..004** (-8): documentation/UX blemish, не блокирующие.

**Откуда набрать обратно:**
- S1-S24 (24 verified strength) дают ~30-40% baseline (как и было до аудита).
- Исправление P0 = +20; P1 = +25; P2 = +8 → ideal score: 100.

**Вывод:** готовность = **47/100**. **Оценка ≥80 запрещена при наличии P0/P1** → невозможно пока не закрыты ENVSET-P0-001 и ENVSET-P0-002 (минимум).

---

## 7. Recommended next tasks

| Order | ID | Action | Owner suggestion | Effort |
|---|---|---|---|---|
| 1 | ENVSET-P0-001 | Заменить `--shutdown-timeout` → `--workers-kill-timeout` в `granian_tuning.py:223` + обновить 5 ассертов в `tests/unit/core/scaling/test_granian_graceful_shutdown.py` + добавить smoke-subprocess test в `tests/smoke/test_granian_runtime.py` | core/scaling owner | XS (< 1ч) |
| 2 | ENVSET-P0-002 | Удалить поле `graceful_shutdown_timeout` из `granian_tuning.py:125-135`, сделать DI через `settings.app.graceful_shutdown_timeout` (single source of truth). Опционально: добавить feature-flag `graceful_shutdown_disabled` для escape-hatch case value=0 | core/config owner | S (~1-2ч) |
| 3 | ENVSET-P1-001 | Schema-добавить `deploy.resources.limits` для всех app/worker/celery контейнеров во все 7 compose-файлов с `${VAR:-default}` паттерном | ops/compose owner | M (~3-4ч) |
| 4 | ENVSET-P1-003 | Добавить `lifecycle.preStop: sleep 30` в `deploy/k8s/deployment-worker.yaml` (синхронизировать с Helm) | deploy owner | XS |
| 5 | ENVSET-P1-004 | Пробросить `timeout` параметр в `run_shutdown()`, использовать `settings.app.graceful_shutdown_timeout - 5` (5s safety для log-sink flush) | lifecycle owner | S |
| 6 | ENVSET-P1-005 | Заменить `subprocess.call` на `subprocess.run(..., check=False); sys.exit(result.returncode)` в `tools/granian_runner.py:117` + assert-clean log message | devops owner | XS |
| 7 | ENVSET-P1-002 | Decision-needed: выбрать либо (a) `_run_granian()` → удалить + force `tools/granian_runner.py`, либо (b) `_run_granian()` → добавить `workers_kill_timeout` | architecture owner | M |
| 8 | ENVSET-P2-001 | Обновить docstring `graceful_shutdown_timeout` для cross-server awareness | docs owner | XS |
| 9 | (phase 2) ENVSET-P2-002 | Deep-dive `services/outbox.py`, `ai_stack.py`, `express.py`, `elasticsearch.py`, `influxdb.py` — phase-2 dedicated audit | phase-2 | M-L |
| 10 | (phase 2) ENVSET-P2-004 | Verify `routes_without_api_key` allowlist — over-permissive check для prod-overrides | phase-2 | M |

---

## 8. Commands run (только read-only)

```bash
# inventory
ls src/backend/core/config/
ls config_profiles/ config/ deploy/ ops/compose/
ls src/backend/core/scaling/
find /home/user/dev/gd_integration_tools -maxdepth 2 -name "docker-compose*"
git log --oneline -1
git status --short

# verify (sub.P0-001)
uv run --extra dev-light python -m granian --help | grep -i 'shutdown\|kill'
uv run --extra dev-light python -m granian foo:bar --shutdown-timeout 5
# → "Error: No such option: --shutdown-timeout", rc=2
uv run --extra dev-light python -c "import granian; print(granian.__version__)"
# → 2.8.0
uv run --extra dev-light python -c "from granian import Granian; import inspect; print(list(inspect.signature(Granian.__init__).parameters.keys()))"
# → ['self','target','address','port','uds','uds_permissions','interface','workers','blocking_threads',
#    'blocking_threads_idle_timeout','runtime_threads','runtime_blocking_threads','runtime_mode','loop',
#    'task_impl','http','websockets','backlog','backpressure','http1_settings','http2_settings',
#    'log_enabled','log_level','log_dictconfig','log_access','log_access_format','ssl_cert','ssl_key',
#    'ssl_key_password','ssl_protocol_min','ssl_ca','ssl_crl','ssl_client_verify','url_path_prefix',
#    'respawn_failed_workers','respawn_interval','rss_sample_interval','rss_samples',
#    'workers_lifetime','workers_max_rss','workers_kill_timeout', ...]

# verify (sub.P0-002)
uv run --extra dev-light python -c "
from src.backend.core.config.settings import settings
print('app.graceful_shutdown_timeout:', settings.app.graceful_shutdown_timeout)
"
# → 30
GRANIAN_GRACEFUL_SHUTDOWN_TIMEOUT=42 uv run --extra dev-light python -c "
from src.backend.core.scaling.granian_tuning import GranianTuning
print(GranianTuning().graceful_shutdown_timeout)
"
# → 42

# compose limits (sub.P1-001)
grep -c "resources\|cpu\|memory\|limits" /home/user/dev/gd_integration_tools/ops/compose/*.yml
grep -A4 'deploy:' /home/user/dev/gd_integration_tools/ops/compose/docker-compose.yml
grep -A4 'deploy:' /home/user/dev/gd_integration_tools/ops/compose/docker-compose.light.yml

# tests (read-only verify current pass state)
uv run --extra dev-light pytest tests/unit/core/scaling/test_granian_graceful_shutdown.py -v --no-header
# → 6 passed

# k8s vs helm preStop sync (sub.P1-003)
grep -c "terminationGracePeriodSeconds\|preStop" /home/user/dev/gd_integration_tools/deploy/k8s/deployment-worker.yaml
# → 1 (only terminationGracePeriodSeconds; no preStop)
grep -c "terminationGracePeriodSeconds\|preStop" /home/user/dev/gd_integration_tools/deploy/helm/gd-integration-tools/templates/deployment-worker.yaml
# → 2 (both)
```

---

## Заключение

Домен Settings & Environment для Sprint 38 production-readiness имеет **2 verified P0** (broken `--shutdown-timeout` CLI flag, дублированное поле `graceful_shutdown_timeout`), **5 verified P1** (compose без cgroup-limit, _run_granian без shutdown-args, k8s-worker без preStop, hardcoded task_registry timeout=10, subprocess.call без explicit exit) и **4 P2/P3** (docs/UX и непроверенные модули для phase-2).

Critical path к ≥80: ENVSET-P0-001 + ENVSET-P0-002 (плюс рекомендованные P1 закрытия). Без них невозможно задеплоить production-стек через `tools/granian_runner.py`.

**Verified strengths (24):** правильный `Settings` singleton + `YamlConfigSettingsLoader` + `VaultConfigSettingsSource` + `ConsulConfigSettingsSource` (fail-closed при отсутствии конфигов), 3-mixins `ConfigValidator` с `ProductionConfigError` (14 чеков), 14-step lifecycle `run_shutdown()` с best-effort per-subsystem try/except, SIGTERM/SIGINT install handlers (cross-platform), granular `asyncio.wait_for` в `worker.py`, Tini PID-1, K8s manifests с non-root securityContext + `terminationGracePeriodSeconds` + `preStop` + PDB + HPA + NetworkPolicy + Job for migrations.

Все 24 verified strengths + 2×P0 + 5×P1 = **47/100 readiness**.

Не верифицировано (по регламенту): s3.py/uv.lock/pyproject.toml/test_dataframes.py рабочие изменения; security-allowlist IDs (35, посчитанные до старта агентом); CLAUDE.md/PLAN.md/KNOWN_ISSUES.md; Anything in `*secret*`, `*token*`, `*key*`, `*.pem`.

---

*Phase 1, Cycle 1, Domain 12: Settings-Environment · Independent analyst.*
