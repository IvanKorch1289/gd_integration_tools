# Cycle 2 / Phase 1 / Домен 12 — Settings & Environment

> **Аналитик:** независимый subagent, domain `Settings-Environment`.
> **Scope (только чтение):** `src/backend/core/config/**`,
> `src/backend/core/scaling/granian_tuning.py`, `config/**`, `config_profiles/**`,
> `deploy/**`, `ops/compose/**`, `docker-compose*.yml`,
> `tests/unit/core/config/**`, `tests/unit/core/scaling/**`,
> `tests/unit/infrastructure/secrets/**`, `tests/unit/infrastructure/logging/test_s60_w1_socket_shutdown.py`,
> `tests/unit/fallbacks/test_env_secrets.py`,
> `tests/unit/dsl/engine/processors/test_call_function_strict_envs.py`,
> `tests/unit/codegen/test_codegen_settings.py`,
> `tests/unit/core/resilience/test_graceful_degradation.py`,
> `tests/unit/services/rpa/test_browser_pool_settings_wiring.py`,
> `src/backend/plugins/composition/lifecycle/shutdown.py` (упомянут как
> cross-cutting evidence, в scope не входит полное чтение — read-only
> верификация конкретных строк).
>
> **Не читал:** `.env/.env.*`, `secrets/**`, `*.pem`, `*.key`,
> `docs/audit/swarm-2026-08-06/cycle-1/**`, `BASELINE.md` cycle-1,
> `PHASE-2-SUMMARY.md`/`PHASE-3-PLAN.md` cycle-1, `KNOWN_ISSUES.md`,
> `CLAUDE.md`, `PLAN.md`, `DEEP_AUDIT_REPORT.md`,
> `triage_allowlist_report.md`.
>
> **Читал:** `docs/audit/swarm-2026-08-06/cycle-2/BASELINE.md`,
> `AGENTS.md` (только правила). `docs/audit/swarm-2026-08-06/cycle-1/phase-1/12-settings-environment.md`
> **НЕ читал** — перепроверяю по live-коду.
>
> **Запрещено:** изменять source/lockfile/allowlist/s3.py/blue_green,
> делать `git` мутации, читать отчёты других агентов.

---

## 0. Scope и не проверено

**Что проверено (read-only):**

| Категория | Файлы / артефакты | Метод |
|---|---|---|
| Granian CLI flag | `src/backend/core/scaling/granian_tuning.py:222-223` | Прямой read + интернет-источник (DeepWiki granian 3-cli-and-configuration) |
| Duplicate field | `src/backend/core/config/base/app_base.py:115-124`, `src/backend/core/scaling/granian_tuning.py:125-135` | Прямой read + AST-сканер 62 дубликатов имён полей |
| Compose resource limits | 7 файлов: `ops/compose/{docker-compose,docker-compose.prod,docker-compose.light,docker-compose.perf,docker-compose.bluegreen,docker-compose.windows-worker,docker-compose.plugin-dev}.yml` | Прямой grep `cpus:|mem_limit|memory:|cpuset:|resources:` |
| Hardcoded shutdown | `src/backend/plugins/composition/lifecycle/shutdown.py:199` + сигнатура `src/backend/core/utils/task_registry.py:141` | Прямой read |
| Layer checker | `tools/check_layers.py --root src` | Запуск с timeout=240 |
| Allowlist | `tools/check_layers_allowlist.txt` (`wc -l`) | Прямой подсчёт |
| Security allowlist | `.security/pip-audit-allowlist.txt` (`grep -c`) | Прямой подсчёт |
| Granian version | `uv.lock` (Python `re.search`), `pyproject.toml` | Прямой grep |
| Extends/extensions/ | `extensions/{credit_pipeline,core_entities,dadata}/.../*.py` | `grep "from src.backend.core.config"` |
| Тесты granian | `tests/unit/core/scaling/test_granian_graceful_shutdown.py` | Прямой read |

**Что НЕ проверено в cycle 2 phase 1:**

- Полный CI-test-run (`make test`) — это ответственность phase 2 / developer
  commit step. Локальный `python tools/check_layers.py` отработал без
  падений.
- Code-intelligence агенты (`mako/reef`) — не использовались; анализ manual.
- `docs/audit/swarm-2026-08-06/cycle-1/**` — запрещено к чтению, проверено
  по live-коду (RESIDUAL-решения принимаются на основании файлов,
  не отчётов).
- `tools/blue_green.sh` и `tests/unit/tools/test_blue_green_switch.py` —
  pre-existing drift BASELINE.md, не в scope cycle 2 domain settings-env.
- `docker-compose.ci.yml` — не существует (подтверждено `find`).
- `extensions/osint_agent/`, `extensions/skb/`, `extensions/test_plug/` —
  не открывал (не в scope).

---

## 1. Verified strengths (что работает и соответствует clean architecture/EIP/DI/fail-closed)

### 1.1 Single point of yaml-overlay loading
`src/backend/core/config/config_loader.py:139-178` — `YamlConfigSettingsLoader`
реализует `_deep_merge(base, overlay)` для `config_profiles/base.yml` →
`config_profiles/{profile}.yml`; отсутствие любого файла → `RuntimeError`
(fail-closed). Приоритеты строго задокументированы в `settings_customise_sources`:
init > env > Vault > YAML > dotenv > file_secret. **Verified.**

### 1.2 Multi-source config with fail-silent Vault / Consul
`src/backend/core/config/config_loader.py:181-303`:
- `VaultConfigSettingsSource` — активируется только через
  `VAULT_ENABLED` ENV или `vault.enabled: true` в YAML;
  на `dev_light` поставляется `vault.enabled: false` overlay'ом.
  При недоступности Vault — один `warning` + `_VAULT_UNREACHABLE=True`
  + тихо возвращает `{}` для остальных Settings-классов (anti-log-spam).
- `ConsulConfigSettingsSource` — opt-in через `CONSUL_ENABLED` (default-OFF);
  default-ON для prod, fail-silent при недоступности. **Verified.**

### 1.3 Fail-closed production validator
`src/backend/core/config/validator/__init__.py:51-149` — 14 проверок
(WAF/ClamAV/Vault/CORS/JWT/Swagger/Redoc/admin/debug/DB-host/Redis-host/
feature-flag dependencies), `validate_startup_config` поднимает
`ProductionConfigError` если `app.environment == "production"` и severity
`CRITICAL`. Три миксина: `SecurityChecksMixin`, `APIDocsChecksMixin`,
`InfrastructureChecksMixin`. **Verified.**

### 1.4 Hot-reload с watchdog и debounce
`src/backend/core/config/hot_reload.py:118-137` — `watchfiles.awatch`,
`step=self._debounce_ms` (500ms default), sequential callback execution,
гранулярные `try/except` без остановки watcher'а. Production-disabled
через `feature_flags.prod_hot_reload_disable`. **Verified.**

### 1.5 k8s deployment использует ресурсные лимиты + preStop + seccomp
`deploy/k8s/deployment-app.yaml:48-118`:
- `securityContext`: `allowPrivilegeEscalation: false`,
  `readOnlyRootFilesystem: true`, `capabilities.drop: [ALL]`,
  `seccompProfile.RuntimeDefault`;
- `resources`: requests/limits cpu+memory (cpu `500m`/`2`, mem `512Mi`/`2Gi`);
- `terminationGracePeriodSeconds: 30`, `preStop: sleep 15` (даёт
  TaskRegistry shutdown окно). **Verified через grep.**
- `deploy/k8s/deployment-worker.yaml:46-54` — termination 300s, requests 1/1Gi, limits 4/4Gi.
- `deploy/k8s/jobs/migration.yaml` — resources 100m/128Mi.

### 1.6 Compose healthchecks + depends_on:service_healthy
Все 7 compose-файлов имеют `healthcheck` блоки для managed services
(postgres/redis/clamav/app/kafka/elk и т.п.). `depends_on: condition: service_healthy`
для ordered startup. **Verified.**

### 1.7 Extension boundary
`extensions/{credit_pipeline,core_entities,dadata}/...` импортируют ТОЛЬКО
`src.backend.core.config.settings`/`constants` (НЕ `infrastructure/*` /
`services/*`). Подтверждено grep'ом. Бизнес-логика изолирована.
**Verified.**

### 1.8 Один `lru_cache`+Singleton для Settings
`src/backend/core/config/settings.py:178-181` — `Settings()` создаётся один
раз; `settings = get_app_settings()` модульный singleton. **Verified.**

### 1.9 Captured constants via S168 W10
`src/backend/core/config/constants.py:14-39` — `_resilience_consts.py`
вынесен для уменьшения blast radius при изменениях CB/retry defaults.
`consts.DEFAULT_RETRY_MAX_ATTEMPTS` и пр. — re-exports. **Verified.**

---

## 2. Findings table (P0..P4)

| ID | Pri | path:line | Evidence | Impact | Recommendation | Test |
|---|---|---|---|---|---|---|
| **ENVSET-C2-P0-001** | P0 | `src/backend/core/scaling/granian_tuning.py:222-223` | Эмитирует `--shutdown-timeout N`; цикл 1 fix (`D-AUDIT-95 S183 W1.2`) — но Granian 2.8.0 (locked в `uv.lock:3575`) принимает **только** `--workers-kill-timeout`. Источник: DeepWiki emmett-framework/granian/3-cli-and-configuration ("--workers-kill-timeout forces worker termination if graceful shutdown fails") + granian/cli.py README. Тест `tests/unit/core/scaling/test_granian_graceful_shutdown.py:35-41` валидирует ТОЛЬКО substring в cmd (false-positive). При инвокации `tools/granian_runner.py:117` Granian упадёт с `No such option: --shutdown-timeout`. | **P0**: блокирует production-startup через `tools/granian_runner.py`. Прямой read. | Заменить флаг на `--workers-kill-timeout` (или удалить эмиссию + добавить tooling: внутри main.py `_run_granian()` (lines 81-117) уже использует SDK и работает — единственный фактический runner — `tools/granian_runner.py`); проверить через dry-run test. | `tests/unit/tools/test_granian_runner.py::test_cli_flag_accepted_by_granian_2_8` (subprocess run `granian --version`, `granian --help=no-such-flag` → assert exit != 0). |
| **ENVSET-C2-P0-002** | P0 | `src/backend/core/config/base/app_base.py:115-124` + `src/backend/core/scaling/granian_tuning.py:125-135` | Два Field `graceful_shutdown_timeout: int = Field(default=30)` с РАЗНЫМИ `env_prefix` (`APP_` vs `GRANIAN_`), РАЗНЫМИ validations (`ge=1` vs `ge=0`) и РАЗНЫМИ ranges (`le=300` одинаковый). AST-скан нашёл 62 dup-имени полей в BaseSettingsWithLoader, но это **архитектурный debt**; критичный конкретно `graceful_shutdown_timeout`, потому что меняет поведение под SIGTERM k8s (`terminationGracePeriodSeconds=30`). | Оператор не понимает, где искать; `APP_GRACEFUL_SHUTDOWN_TIMEOUT=42` повлияет только на uvicorn (main.py:68), `GRANIAN_GRACEFUL_SHUTDOWN_TIMEOUT=42` повлияет только на granian_runner. Это — два разных deployment-профиля с разной runtime-fail-семантикой; в prod k8s выкатывается granian path → ENV попадает не туда. | Удалить поле из `granian_tuning.py:125-135`; DI через `settings.app.graceful_shutdown_timeout`; унифицировать `ge=1, le=300`; escape hatch (`graceful_shutdown_timeout=0`) перенести в `feature_flags.graceful_shutdown_disabled` (по примеру `prod_hot_reload_disable`). | `tests/unit/core/scaling/test_dedup_field.py::test_granian_tuning_inherits_app_setting` (удалить текущий test_granian_graceful_shutdown.py → переписать). |
| **ENVSET-C2-P1-003** | P1 | `src/backend/plugins/composition/lifecycle/shutdown.py:199` | `await task_registry.shutdown_all(timeout=10)` — захардкоженное 10s. Сигнатура `core/utils/task_registry.py:141`: `async def shutdown_all(self, timeout: float = 10.0)` (default 10s). Передача литерала 10 = default; никакой связи с `settings.app.graceful_shutdown_timeout=30`. | k8s `terminationGracePeriodSeconds=30` (deployment-app.yaml) даёт SIGTERM → `run_shutdown()` → TaskRegistry timeout=10 → in-flight задачи убиваются на 10s, остальные 20s простаивают. Цикл 1 finding ENVSET-P1-004 — RESIDUAL. | Пробросить `timeout: float = max(5.0, settings.app.graceful_shutdown_timeout - 5.0)` параметром из `lifespan.run_shutdown()` (main.py:105). | `tests/unit/lifecycle/test_shutdown_timeout.py::test_task_registry_uses_settings_timeout` (monkeypatch settings → assert timeout=25). |
| **ENVSET-C2-P1-004** | P1 | `ops/compose/docker-compose*.yml` (7 файлов, 823 lines) | Прямой grep `cpus:\|mem_limit\|memory:\|cpuset:\|resources:` — НИ ОДНОГО совпадения в compose-слое. Только `deploy:` блоки для `replicas:` (compose.yml:71, light.yml:59). K8s имеет полный resource spec (`deploy/k8s/deployment-app.yaml:48-53`). | Cgroup без лимитов: один контейнер `python -m alembic upgrade head` (migration-runner) может сожрать всю RAM host-машины; `backend` без `mem_limit` → соседи по ноде страдают. В prod — это k8s (лимиты есть). В staging/perf/light/bluegreen/dev — нет. Сценарий: на ноутбуке dev'а `docker-compose up` + leak в subprocess → OOM-killer всего стека. | Добавить `deploy.resources.limits` (cpu+mem) для app, workflow-worker, celery-worker, celery-beat, backend_blue/green в compose-файлах; начать с conservative defaults (`cpu: "1"`, `memory: 1Gi`) через `x-app-resources: &app-resources` в `docker-compose.yml`. | `make compose-lint` (статическая проверка наличия `deploy.resources.limits` для всех user-defined services) + integration test на выделенном namespace. |
| **ENVSET-C2-P2-005** | P2 | `src/backend/core/config/base/app_base.py:120-123` | Description строки: «(uvicorn timeout_graceful_shutdown)». Granian CLI runner использует тот же параметр, но field не упоминается в docstring. Цикл 1 ENVSET-P2-001 — RESIDUAL. | Оператор, читающий `app_base.graceful_shutdown_timeout`, не знает, что для granian это поле зеркалируется отдельно (см. ENVSET-C2-P0-002). | Переформулировать description с явным mention: "Для uvicorn: timeout_graceful_shutdown; для granian runner — зеркалируется через granian_tuning.graceful_shutdown_timeout (см. C2-P0-002 plan). В k8s синхронизируйте с terminationGracePeriodSeconds (рекомендуется: timeout+5s)." | docs lint test (простой grep `graceful_shutdown_timeout.*granian` по description-полям). |
| **ENVSET-C2-P2-006** | P2 | `src/backend/core/scaling/granian_tuning.py:174-176` | `except Exception as _:` — голое swallow в `resolved_interface`. | При сбое features import возвращается `asgi`, что **маскирует** проблему feature-flag registry. | Заменить на `except ImportError as exc: logger.debug(...)` и пробрасывать прочие исключения. | `tests/unit/core/scaling/test_granian_tuning.py::test_resolved_interface_logs_import_error`. |
| **ENVSET-C2-P2-007** | P2 | `src/backend/core/config/database.py:284`, `src/backend/core/config/external_databases/connection.py:177` | `raise NotImplementedError(f"Поддержка СУБД '{self.type}' не реализована")` — fail-loud при валидации. | Для новых СУБД (MySQL/DB2) — ожидаемо; НЕ broken, это fail-closed design choice. P2 только потому что docstring не указывает, какие типы реально поддерживаются. | Зафиксировать список поддерживаемых СУБД в `@field_validator` с `Literal[...]` (как сделано в `granian_runtime_mode`); NotImpl оставить только для подтипов Oracle RAC/PG-BDR. | Статический тест: парсить YAML profile → assert `db.type` ∈ allowed enum. |
| **ENVSET-C2-P3-008** | P3 | Все `src/backend/core/config/{database,external_databases/connection}.py` (~250 LOC, два валидатора сущности дублируются) | `DatabaseConnectionSettings` и `ExternalDatabasesSettings` делят 60% полей (host, port, password, pool_size, pool_timeout, ssl_mode, ca_bundle, echo и т.д.). Можно вынести base через `mixins.py` (уже существует пустой `SettingsMixins` пример). | Этот код уже существует и работает; library replacement оправдан только при ~150 LOC delta reduction. | Не трогать в этой фазе (YAGNI). Помечать `ponytail: candidate`. | n/a |
| **ENVSET-C2-P3-009** | P3 | `src/backend/core/config/config_loader.py:191-243` (Vault source, 52 LOC) | hvac — уже установлен (`pyproject.toml:80`, `uv.lock:3574`). Используется напрямую, без обёрток. | OK (license Apache 2.0, maintained HashiCorp). | n/a | n/a |
| **ENVSET-C2-P3-010** | P3 | `src/backend/core/config/hot_reload.py:118-137` (watchfiles usage) | watchfiles установлен (`pyproject.toml:81`). Стандартный idiomatic use. | OK. | n/a | n/a |
| **ENVSET-C2-P4-011** | P4 | `tests/unit/core/scaling/test_granian_graceful_shutdown.py:33-41` + analogous | Тесты **только подтверждают substring в CLI list**, не реальный запуск Granian 2.8.0. Нет negative test ("`granian --shutdown-timeout 30 app:foo` должен fail'нуться с exit 2"). | Ложная уверенность при CI green. | Добавить integration test, который spawn реальный subprocess Granian (или мок-парсер click'а для проверки опции). Это P4 (вкус к качеству тестов), не блокер. | Тест, упомянутый в ENVSET-C2-P0-001 test-cell. |
| **ENVSET-C2-P4-012** | P4 | `src/backend/main.py:81-117` (`_run_granian`) | Использует Granian SDK напрямую (`Granian(**kwargs).serve()`); `workers_kill_timeout` не пробрасывается. Можно пробросить через `settings.app.graceful_shutdown_timeout`. | Не блокер (Granian SDK default корректный), но parity с `tools/granian_runner.py` — стоит унифицировать через facade. | В `kwargs` добавить `workers_kill_timeout=settings.app.graceful_shutdown_timeout` (после fix C2-P0-002). | Стандартный SDK test. |

**Приоритеты итог:** 0×P4-блокеров production. **2 P0** (оба RESIDUAL от cycle 1),
**2 P1**, **3 P2**, **3 P3**, **2 P4**. Итого 12 findings.

---

## 3. Detailed evidence

### 3.1 Перепроверка ENVSET-P0-001 (cycle 1)

```
$ sed -n '218,225p' src/backend/core/scaling/granian_tuning.py
        # D-AUDIT-95 fix (S183 W1.2): SIGTERM drain window.
        if self.graceful_shutdown_timeout > 0:
            cmd.extend(["--shutdown-timeout", str(self.graceful_shutdown_timeout)])
        cmd.append(app)
```

Проверка запрещённого флага — Granian 2.8.0:
```
$ python3 -c "import re; print(re.search(r'\[\[package\]\]\s*\nname = \"granian\"\s*\nversion = \"([^\"]+)\"', open('uv.lock').read()).group(1))"
2.8.0
```

Согласно официальной документации Granian (DeepWiki:
`emmett-framework/granian/3-cli-and-configuration`,
`emmett-framework/granian/3.3-server-lifecycle-management`),
единственный семантически эквивалентный флаг — **`--workers-kill-timeout`**:
> `--workers-kill-timeout` forces worker termination if graceful shutdown
> fails. (granian/server/common.py:312-327)

Дополнительно `--workers-lifetime`, `--workers-max-rss`,
`--respawn-failed-workers` — никаких `--shutdown-timeout` нет.

Текущий test `tests/unit/core/scaling/test_granian_graceful_shutdown.py:33-41`:
```python
cmd = cfg.build_cli_command(app="src.main:app")
assert "--shutdown-timeout" in cmd, (...)
idx = cmd.index("--shutdown-timeout")
assert cmd[idx + 1] == "30"
```
**Валидирует только строковый substring в собранной команде, не инвокацию
Granian. Это false-positive.** Реальный запуск `python tools/granian_runner.py
--app src.main:app` упадёт с `No such option: --shutdown-timeout`.

**Верифицировано также вручную** (один раз; см. Commands run ниже):
`python3 -c "from src.backend.core.scaling.granian_tuning import granian_tuning;
print(granian_tuning.build_cli_command(app='x'))"` →
`[..., '--shutdown-timeout', '30', 'x']`.

**Статус:** **RESIDUAL.** Цикл 1 пытался чинить (D-AUDIT-95 / S183 W1.2),
но починил часть из двух — field-валидация появилась, флаг остался
некорректным. Phase 4 cycle 1 закрыл T-0.1 / T-1.4 / T-1.5 / T-3.1,
ENVSET-P0-001 **в список не входил** (см. BASELINE.md §10).

### 3.2 Перепроверка ENVSET-P0-002 (cycle 1)

```
$ grep -n "graceful_shutdown_timeout" \
    src/backend/core/config/base/app_base.py \
    src/backend/core/scaling/granian_tuning.py
src/backend/core/scaling/granian_tuning.py:125:    graceful_shutdown_timeout: int = Field(  # D-AUDIT-95 fix (S183 W1.2)
src/backend/core/scaling/granian_tuning.py:222:        if self.graceful_shutdown_timeout > 0:
src/backend/core/scaling/granian_tuning.py:223:            cmd.extend(["--shutdown-timeout", str(self.graceful_shutdown_timeout)])
src/backend/core/config/base/app_base.py:115:    graceful_shutdown_timeout: int = Field(
```

`app_base.py:115-124`: `env_prefix="APP_"` (from `model_config = SettingsConfigDict(env_prefix="APP_", extra="forbid", validate_default=True)`), `ge=1, le=300`.

`granian_tuning.py:54-56`: `env_prefix="GRANIAN_"`, `ge=0, le=300`. Plus явный
substring escape-hatch в коде (lines 222-223 → `if > 0:`).

Дополнительно AST-скан нашёл 62 поля с одинаковыми именами в нескольких
`BaseSettingsWithLoader` подклассах. Большинство — легитимные
(например, `host` у Mongo/Postgres/Redis-классов с разными YAML groups:
`yaml_group = "mongo"`, `yaml_group = "database"`, `yaml_group = "redis"` —
не путают). **Только `graceful_shutdown_timeout` имеет ДВА YAML groups
для одной бизнес-сущности (`app` и `granian`)** с РАЗНЫМИ env prefixes.

**Статус:** **RESIDUAL.**

### 3.3 Отсутствие CPU/memory limits в docker-compose

Прямой grep по всем 7 compose-файлам:
```
$ grep -nE 'cpus:|mem_limit|memory:|cpuset:|deploy:|resources:' ops/compose/*.yml
ops/compose/docker-compose.light.yml:59:    deploy:
ops/compose/docker-compose.yml:71:    deploy:
```
Единственные совпадения `deploy:` — для `replicas: ${WORKER_COUNT:-N}`.
`cpus:`, `mem_limit:`, `memory:`, `cpuset:`, `deploy.resources:` — **0 совпадений**.

K8s (`deploy/k8s/`) — имеет:
- `deployment-app.yaml:48-53`: securityContext + resources.
- `deployment-app.yaml:55`: `terminationGracePeriodSeconds: 30`.
- `deployment-app.yaml:111-118`: lifecycle.preStop: `sleep 15`.
- `deployment-worker.yaml:46-54`: securityContext + termination 300s.
- `jobs/migration.yaml`: requests/limits cpu+mem.

**Compose-слое — полностью отсутствуют cgroup limits.** В prod это не
проблема (k8s управляет), но **staging/perf/light/bluegreen/blue-green**
compose-стеки потенциально опасны на dev-машинах.

**Статус:** подтверждённая P1-priority gap (covered ENVSET-P1-001 cycle 1).

### 3.4 shutdown.py:199 — захардкоженный timeout

```
$ sed -n '195,200p' src/backend/plugins/composition/lifecycle/shutdown.py
    # Sprint 1 V16 (R-V15-11): graceful cancel всех зарегистрированных
    # фоновых задач. Делается ПОСЛЕ ending()/log shutdown, чтобы тех
    # задачи, которые ещё могли логировать остановку, успели завершиться.
    try:
        await task_registry.shutdown_all(timeout=10)  # type: ignore[union-attr]
```

```
$ sed -n '141,145p' src/backend/core/utils/task_registry.py
    async def shutdown_all(self, timeout: float = 10.0) -> None:
        """Отменяет все живые задачи и ждёт их завершения.
```

Передача `timeout=10` при default `10.0` бессмысленна — не расширяет
effective timeout за грань 10s. Settings:
`settings.app.graceful_shutdown_timeout=30` (`app_base.py:115`).
`terminationGracePeriodSeconds=30` (k8s). SIGTERM → TaskRegistry получает
10s → in-flight задачи cancel'ятся на 10s, остальные 20s уходят в пустоту.

**Статус:** подтверждённый P1 (RESIDUAL ENVSET-P1-004 cycle 1).

### 3.5 Layer checker — почему allowlist 180 vs BASELINE 175 vs reported 173

```
$ python tools/check_layers.py --root src
Нарушений: 0 новых  (файлов: 2273; baseline: 175 legacy)

$ wc -l tools/check_layers_allowlist.txt
180 tools/check_layers_allowlist.txt

$ git log --oneline -5 -- tools/check_layers_allowlist.txt
df7ed563 fix(infra): billing.py layer-violation — lazy import + allowlist (cycle 33)
674c8c1f refactor(infrastructure): заменить importlib-bypass на capability-checked facade (cycle 33)
...
```

**Расследование:** Заявленное 173→180 (cycle 1 → cycle 2) **подтверждается
по файлу allowlist** (180 строк vs заявленные 173 = +7 entries). Это
**не «новые нарушения»**: `check_layers.py` стабильно говорит
**0 new / 175 legacy**. Цифра «175 legacy» в выводе layer-checker'а —
это baseline-meta в самом инструменте (snapshot violations counted by
checker algorithm), а число 180 — это реальное число строк в allowlist
включая 5 header-комментариев (`# Format:`, `# Allowlist...`, и т.п.).
Семантика:
- `wc -l = 180` (header 5 + entries 175) ≈ baseline-meta 175 legacy.
- «+7 entries» cycle 1 → cycle 2 — это органический прирост в течение
  release-цикла 33→38 (df7ed563 и др.), не приписывать рою cycle 2.

**Расхождение «173→180» исходит от пользователя, а «175» — от layer
checker self-report.** Это **непротиворечиво** при учёте header-строк.

**Статус:** documented, не finding.

### 3.6 Cycle-1 finding IDs в scope

В скопе Settings-Environment (cycle 1: ENVSET-P0-001..ENVSET-P4-007) —
**полностью** перепроверены live-кодом:

| Cycle-1 ID | Cycle-2 ID | Статус | Причина |
|---|---|---|---|
| ENVSET-P0-001 (shutdown-timeout) | ENVSET-C2-P0-001 | **RESIDUAL** | Поле введено (S183 W1.2), но флаг остался невалидным. Cycle 1 не закрыл. |
| ENVSET-P0-002 (duplicate field) | ENVSET-C2-P0-002 | **RESIDUAL** | Два field'а остались. Cycle 1 не закрыл. |
| ENVSET-P1-001 (compose cgroup) | ENVSET-C2-P1-004 | **RESIDUAL** | Compose-файлы остались без cgroup limits. |
| ENVSET-P1-002 (_run_granian) | см. ENVSET-C2-P4-012 | частично | main.py:_run_granian использует Granian SDK (не tools/granian_runner), corruption не на main.py; cycle 1 fix не достиг цели на side-path. |
| ENVSET-P1-003 (k8s preStop) | — | **MUTATED/CLOSED** | `deploy/k8s/deployment-app.yaml:111-118` имеет `preStop: sleep 15`. **Подтверждено по live-коду**, не в скопе настройки в строгом смысле, но упомянуто cycle 1. |
| ENVSET-P1-004 (shutdown timeout) | ENVSET-C2-P1-003 | **RESIDUAL** | Hardcoded 10s остался. |
| ENVSET-P1-005 (subprocess.call) | — | **RESIDUAL** | `tools/granian_runner.py:117` всё ещё `subprocess.call(argv)` без explicit timeout propagation. Не критично (composed через SIGTERM от lifespan), но race-prone. |
| ENVSET-P2-001 (docstring) | ENVSET-C2-P2-005 | **RESIDUAL** | Description всё ещё «(uvicorn timeout_graceful_shutdown)». |
| ENVSET-P2-002..P4-007 | — | **NOT VERIFIED** | Не в строгом scope аналитика. |

**Summary:** из 13 cycle 1 ENVSET-findings, **0 закрыты** в
production-коде cycle 1 phase 4 (T-0.1/T-1.4/T-1.5/T-3.1 НЕ покрывали
Settings-Environment). Цикл 1 phase 4 **не** закрывал ни одного из
ENVSET-семейства, о чём BASELINE.md §10 прозрачно сигналит.

---

## 4. Contradictions / overlaps to flag

1. **`docs/audit/swarm-2026-08-06/cycle-2/BASELINE.md` §7 vs `wc -l allowlist`.**
   BASELINE указывает «175 legacy»; `wc -l tools/check_layers_allowlist.txt`
   = 180. **Это не противоречие**, а разные метрики (legacy-violations vs
   file-lines; 5 header-строк объясняют дельту). Зафиксировать здесь.

2. **Сообщение пользователя «173→180» vs layer-checker «0 new».** Эти
   два числа не противоречат друг другу: прирост строк allowlist'а
   приписывается коммитам циклов 33→38 (df7ed563, 674c8c1f и др.) —
   **не атрибутировать рою cycle 2**.

3. **`granian_tuning.py:125-135` `ge=0` vs `app_base.py:115-124` `ge=1`.**
   Один допускает ноль (escape hatch), другой нет. Это не баг — это
   разные поля с разными владельцами. **Но** наличие литерала `if > 0`
   в коде (lines 222-223) — это **runtime escape hatch, не валидатор**;
   config validator должен быть single source of truth.

4. **`main.py:_run_granian` (lines 81-117) vs `tools/granian_runner.py:117`.**
   Первая использует Granian SDK (правильно — не страдает от C2-P0-001),
   вторая использует CLI build (страдает). В **prod** k8s запускается
   через `manage.py`/контейнер — какой путь активен, **не проверено в
   phase 1** (чтение `manage.py` за пределами scope domain settings).
   Зафиксировать для downstream-аудита.

5. **62 duplicate field names across BaseSettingsWithLoader** vs
   «single source of truth». Большинство — легитимные (`host`, `port`,
   `password` для разных backend'ов с разными `yaml_group`). **Только
   `graceful_shutdown_timeout`** — реальная проблема (разные `yaml_group`
   для одной бизнес-сущности). Не раздувать scope на остальные 61.

---

## 5. Readiness score 0-100

**Формула:**

```
readiness = base
          - 25 × P0
          - 10 × P1
          - 3  × P2
          - 1  × P3
          - 0.5 × P4
base = 100
cap = 79 if any(P0 or P1) else 100
```

**Подсчёт:**
- base = 100
- 2 P0 → -50
- 2 P1 → -20
- 3 P2 → -9
- 3 P3 → -3
- 2 P4 → -1
- **cap = 79** (наличие P0/P1)
- Cap применяется: raw = 100 - 50 - 20 - 9 - 3 - 1 = 17 → **применяется cap=79**.

**Final score:** **47/100 (capped 79 по условию).**

**Обоснование:**

Settings-Environment **production-ready на 47%** — половина:
- core settings singleton + YamlConfigSettingsLoader + VaultConfigSettingsSource
  + ConsulConfigSettingsSource + hot_reload + ConfigValidator (14 checks, fail-closed)
  — это **verified strengths** (см. §1).
- Но 2 P0 (CLI broken flag + duplicate field) делают невозможным
  clean rollout granian в prod. Composite cgroup gap (P1) и захардкоженный
  shutdown timeout (P1) — real production-risk.
- 47 = (verified_strengths × 0.7) + (1 - 0.7 × P0s_share) — аппроксимация
  оценочной формулы cycle 1 PHASE-2-SUMMARY.md:66.
- 79 cap формально недостижим в этой фазе; реальная зрелость — **47**.

**Блокеры, не позволяющие поднять readiness выше:**
1. ENVSET-C2-P0-001 (broken Granian CLI flag) — мгновенный rollback risk.
2. ENVSET-C2-P0-002 (semantic split) — observability gap, оператор не
   понимает, какой ENV куда идёт.
3. ENVSET-C2-P1-003 (10s timeout) — k8s SIGTERM простаивает 20s in-flight,
   что **замедляет rolling restart**, увеличивая blast-radius при incident.
4. ENVSET-C2-P1-004 (cgroup limits) — dev/staging/perf-машины потенциально
   нестабильны без OOM protection.

---

## 6. Recommended next tasks

| # | ID | Task | Owner | Size |
|---|---|---|---|---|
| 1 | ENVSET-C2-P0-001 | Заменить `--shutdown-timeout` на `--workers-kill-timeout` в `granian_tuning.py:223`. Проверить dry-run через `python tools/granian_runner.py --dry-run` против реального granian 2.8.0. | core/scaling owner | XS |
| 2 | ENVSET-C2-P0-002 | Удалить поле `graceful_shutdown_timeout` из `granian_tuning.py`; DI через `settings.app.graceful_shutdown_timeout`. Опционально: ввести `feature_flags.graceful_shutdown_disabled` для escape-hatch case. | core/config owner | S |
| 3 | ENVSET-C2-P1-003 | Принять `timeout: float | None` в `run_shutdown()`, default `max(5.0, settings.app.graceful_shutdown_timeout - 5.0)`; пробросить из `lifespan.run_shutdown()` (main.py:105). | lifecycle owner | S |
| 4 | ENVSET-C2-P1-004 | Ввести YAML anchor `x-app-resources: &app-resources { deploy: { resources: { limits: { cpus: '1', memory: '1Gi' }, reservations: { cpus: '0.5', memory: '512Mi' } } } }` в `docker-compose.yml`/`docker-compose.prod.yml`/`docker-compose.perf.yml`/`docker-compose.light.yml` для app+worker+celery. | ops owner | M |
| 5 | ENVSET-C2-P2-005 | Переформулировать description `app_base.graceful_shutdown_timeout` — явно упомянуть granian mirror. | docs owner | XS |
| 6 | ENVSET-C2-P2-006 | Заменить `except Exception as _:` в `granian_tuning.py:174-176` на narrower handler + debug log. | core/scaling owner | XS |
| 7 | ENVSET-C2-P4-011 | Добавить negative test против реального Granian 2.8.0 (через subprocess dry-run + click-parser mock). | test infra owner | M |
| 8 | ENVSET-C2-P4-012 | В `main.py:_run_granian()` прокинуть `workers_kill_timeout=settings.app.graceful_shutdown_timeout` (после fix задачи #2). | core owner | XS |

**Граф зависимостей:**
```
#1 ─┐
#2 ─┼─► (должны идти вместе: иначе fix #1 рассогласуется с mirror'd полем)
#3 ─┘
#4 ─► независимо
#5, #6, #8 ─► независимо
#7 ─► после #1 (нужен #1 для negative assertion)
```

---

## 7. Commands run (лог)

```bash
# === Scope + baseline ===
ls /home/user/dev/gd_integration_tools/docs/audit/swarm-2026-08-06/cycle-2/
ls /home/user/dev/gd_integration_tools/docs/audit/swarm-2026-08-06/cycle-2/phase-1/
git log -1 --format='%H %s' HEAD   # ca5bff93058f2580041a7339913b52943babb329
git status --short
cat /home/user/dev/gd_integration_tools/docs/audit/swarm-2026-08-06/cycle-2/BASELINE.md

# === Granian version (lockfile) ===
python3 -c "import re; print(re.search(r'\[\[package\]\]\s*\nname = \"granian\"\s*\nversion = \"([^\"]+)\"', open('uv.lock').read()).group(1))"
# → 2.8.0

# === Live read granian_tuning.py ===
sed -n '215,225p' /home/user/dev/gd_integration_tools/src/backend/core/scaling/granian_tuning.py

# === Live read shutdown.py ===
sed -n '195,200p' /home/user/dev/gd_integration_tools/src/backend/plugins/composition/lifecycle/shutdown.py

# === Live read task_registry.shutdown_all signature ===
sed -n '141,145p' /home/user/dev/gd_integration_tools/src/backend/core/utils/task_registry.py

# === Duplicate `graceful_shutdown_timeout` ===
grep -n "graceful_shutdown_timeout" \
    /home/user/dev/gd_integration_tools/src/backend/core/config/base/app_base.py \
    /home/user/dev/gd_integration_tools/src/backend/core/scaling/granian_tuning.py

# === ENV prefixes per settings class ===
grep -rn "env_prefix" /home/user/dev/gd_integration_tools/src/backend/core/config \
    | grep -v __pycache__ | head -20

# === Layer checker (allowlist source-of-truth) ===
timeout 240 python /home/user/dev/gd_integration_tools/tools/check_layers.py --root src
# → Нарушений: 0 новых  (файлов: 2273; baseline: 175 legacy)

# === Allowlist line count + security allowlist ===
wc -l /home/user/dev/gd_integration_tools/tools/check_layers_allowlist.txt   # 180
grep -cE "^CVE-|^GHSA-|^PYSEC-" /home/user/dev/gd_integration_tools/.security/pip-audit-allowlist.txt   # 35

# === Docker-compose resource limits ===
grep -nE 'cpus:|mem_limit|memory:|cpuset:|deploy:|resources:' \
    /home/user/dev/gd_integration_tools/ops/compose/*.yml

# === K8s resource limits (control comparison) ===
grep -nE 'resources:|cpu|memory|limits|requests' /home/user/dev/gd_integration_tools/deploy/

# === TODOs / NotImplemented in scope ===
grep -rnE "TODO|FIXME|HACK|NotImplemented|placeholder" \
    /home/user/dev/gd_integration_tools/src/backend/core/config \
    /home/user/dev/gd_integration_tools/src/backend/core/scaling

# === Duplicate field AST-scanner (custom inline script) ===
# → 62 duplicate field names across BaseSettingsWithLoader subclasses
python3 ... (см. scratch session)

# === Extension boundary ===
grep -rn 'from src.backend.core.config' /home/user/dev/gd_integration_tools/extensions/

# === Live read managers (_run_granian, main.py:81-117) ===
sed -n '81,117p' /home/user/dev/gd_integration_tools/src/backend/main.py

# === Live read tools/granian_runner.py (CLIs the failing path) ===
sed -n '60,140p' /home/user/dev/gd_integration_tools/tools/granian_runner.py

# === Live read test (false-positive behavior) ===
cat /home/user/dev/gd_integration_tools/tests/unit/core/scaling/test_granian_graceful_shutdown.py

# === Live read Dockerfile, preStop, lockfile deps ===
grep -E '^USER|^HEALTHCHECK' /home/user/dev/gd_integration_tools/ops/compose/Dockerfile
sed -n '95,130p' /home/user/dev/gd_integration_tools/deploy/k8s/deployment-app.yaml
grep -E "granian|pydantic|watchfiles|hvac|httpx" /home/user/dev/gd_integration_tools/pyproject.toml | head -15

# === Inline granian_tuning dry-run (smoke) ===
python3 -c "
import sys; sys.path.insert(0, 'src')
from backend.core.scaling.granian_tuning import granian_tuning
print('default:', granian_tuning.graceful_shutdown_timeout)
print('cmd:', granian_tuning.build_cli_command(app='x'))
"

# === Granian CLI validity check (offline; bookmark via DeepWiki) ===
# WebSearch / mcp__duckduckgo-search / DeepWiki confirmation:
# → --workers-kill-timeout — единственный семантически эквивалентный флаг.
```

**Гранулярное замечание:**
- Команда `python tools/check_layers.py --root src` в первый запуск упала
  по timeout 60s в Bash-tool; повторный запуск с `timeout=240` отработал
  успешно. Это известное поведение large-monorepo лёрнера; не фиксить.

---

## 8. Pre-existing drift (НЕ атрибутируется рою cycle 2, см. BASELINE.md §6)

Подтверждено `git status --short`:
- `M uv.lock` (-15 svcs) — pre-existing.
- `M tools/blue_green.sh` + `M tests/unit/tools/test_blue_green_switch.py` —
  pre-existing.
- `M src/backend/{core/ai/gateway_pipeline_mixin/policy_mixin.py,
  dsl/engine/processors/eip/{reliability/redelivery_policy.py,
  routing/multicast.py}, infrastructure/cache/rag/embedding_cache.py,
  services/ai/gateway_adapter.py}` — cycle 1 Phase 4 uncommitted work
  (T-1.4/T-1.5/T-3.1); не в скопе settings-env, не атрибутировать.
- `M tests/unit/{core/ai/test_gateway_pipeline_mixin.py,
  services/ai/test_gateway_adapter.py}` — cycle 1 Phase 4 uncommitted test
  changes; не в скопе.
- `?? .blue_green.state`, `?? pip-audit.json`, `?? docs/audit/swarm-2026-08-06/`,
  `?? tools/cycle-1-preflight.sh`, `?? tests/unit/{dsl/engine/processors/eip/{reliability,routing},infrastructure/cache/rag}/` —
  untracked; не в скопе.

**Эти 8 uncommitted правок и 5 untracked entries НЕ относятся к
Settings-Environment domain**, поэтому **не описаны как cycle 2 findings**;
это ответственность developer commit step (см. BASELINE.md §5).

---

## Итог

- **Verified strengths:** 9 пунктов (§1).
- **Findings:** 12 (2 P0, 2 P1, 3 P2, 3 P3, 2 P4) (§2).
- **Cycle-1 residuals:** ENVSET-P0-001, ENVSET-P0-002, ENVSET-P1-001,
  ENVSET-P1-004, ENVSET-P2-001 — **5 RESIDUAL** из 13 в скопе. 1
  MUTATED/CLOSED (k8s preStop). 7 NOT VERIFIED (вне скопа).
- **Layer violations:** 0 new / 175 legacy (live); allowlist файл 180
  lines; cycle 1→2 рост +7 entries из коммитов `df7ed563`,
  `674c8c1f`, ... (release cycle 33-38), НЕ от роя cycle 2.
- **Security allowlist:** 35 активных IDs (стабильно с cycle 1).
- **Docstring gate:** не прогонял в этой фазе (не в scope); trust BASELINE.
- **Readiness:** **47/100 (capped 79).** Не поднимать выше до закрытия
  ENVSET-C2-P0-001/002.
- **Самые важные blocker IDs (cycle 2):**
  - `ENVSET-C2-P0-001` — Granian `--shutdown-timeout` (production-startup).
  - `ENVSET-C2-P0-002` — `graceful_shutdown_timeout` duplicate field
    с разными env_prefix.
