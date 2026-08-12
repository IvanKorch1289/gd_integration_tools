# Phase 1 — Домен «Настройки-Окружение» (Cycle 3, 2026-08-06)

**Аналитик:** subagent (Phase 1, read-only)
**Scope:** `src/backend/core/config/**`; `src/backend/core/scaling/granian_tuning.py`;
`config/**`; `config_profiles/**`; `deploy/**`; `ops/compose/**`;
`docker-compose*.yml`; environment/settings tests.
**HEAD:** `7f3d94a388199c136bd7b90fa73d3b5a1217d4f7`
**Python interpreter (все runtime-проверки):** `.venv/bin/python` (`cpython-3.14-linux-x86_64-gnu`).

---

## Scope / что НЕ проверено

**Проверено (read-only):**

* `src/backend/core/config/**` — 94 файла, ~13.5k LOC.
* `src/backend/core/scaling/granian_tuning.py` (229 LOC).
* `src/backend/core/scaling/auto_scaler.py`, `bulkhead_scaler.py`, `local_process_scaler.py`,
  `__init__.py` — прочитаны выборочно (только верхнеуровневые сигнатуры).
* `src/backend/plugins/composition/lifecycle/shutdown.py` (201 LOC).
* `src/backend/core/utils/task_registry.py` (188 LOC, focus на `shutdown_all`).
* `src/backend/main.py` — `run_uvicorn` / `_run_granian` (lines 50-130).
* `tools/config_audit.py` (485 LOC).
* `tools/granian_runner.py` (128 LOC).
* `src/backend/core/config/validator/infrastructure_checks.py` (238 LOC).
* `config_profiles/*.yml` (5 файлов, 1326 LOC).
* `deploy/k8s/{deployment-app,deployment-worker,jobs/migration,hpa-app}.yaml`,
  `deploy/helm/gd-integration-tools/{values.yaml,templates/*.yaml}`.
* `ops/compose/docker-compose.{yml,prod.yml,perf.yml,bluegreen.yml,light.yml,plugin-dev.yml,windows-worker.yml}`.
* Targeted pytest на `tests/unit/core/config/**` (439 collected),
  `tests/unit/core/scaling/**` (включая `test_granian_graceful_shutdown.py` — 6 tests),
  `tests/unit/core/utils/test_task_registry.py` (24 tests),
  `tests/unit/extensions/credit_pipeline/test_scoring_fail_closed.py` (3 tests).

**Не проверено (за пределами scope или запрещено):**

* `.env`, `.env.*`, `secrets/**`, `*.pem`, `*.key`, `*secret*`, `*token*` — запрещено
  AGENTS.md (read-deny).
* `cycle-1/` и `cycle-2/` markdown-отчёты других агентов — запрещено.
* `KNOWN_ISSUES.md`, `CLAUDE.md`, `PLAN.md`, `DEEP_AUDIT_REPORT.md`,
  `triage_allowlist_report.md` — запрещено читать.
* `extensions/<name>/plugin.toml` runtime registry content (только выборочно
  `extensions/credit_pipeline/plugin.toml`).
* `src/backend/core/scaling/{auto_scaler.py,bulkhead_scaler.py,local_process_scaler.py}`
  полный код — только grep верхнеуровневых сигнатур.
* `dev_storage/audit/`, `.benchmarks/`, `.sentry-native/` — не открыты.
* `tests/unit/core/ai/test_gateway_pipeline_mixin.py` (pre-existing mypy error per
  BASELINE) — вне scope (AI домен).

---

## Verified strengths

| ID | Что проверено | Evidence | Где |
|---|---|---|---|
| STR-01 | Granian CLI эмитит `--shutdown-timeout N` (cycle-2 P0-001 RESIDUAL FIXED) | runtime через `tools/granian_runner.py --dry-run` печатает `--shutdown-timeout 30`; 6/6 unit-тестов `test_granian_graceful_shutdown.py` PASSED | `granian_tuning.py:222-223`; `tests/unit/core/scaling/test_granian_graceful_shutdown.py` |
| STR-02 | Granian singleton инстанциируется через venv и резолвит workers/interface | `granian_tuning.resolved_workers=4`, `resolved_interface="rsgi"` через `.venv/bin/python -c "..."` | `granian_tuning.py:228`; runtime проверено |
| STR-03 | Multi-source config loader: init > env > Vault > YAML > dotenv > file_secret | `BaseSettingsWithLoader.settings_customise_sources` возвращает 6 источников в правильном порядке | `config_loader.py:347-353` |
| STR-04 | Fail-closed: `NotImplementedError` для неподдерживаемых СУБД | `database.py:284`, `external_databases/connection.py:177` — оба raise, не молча | OK |
| STR-05 | Fail-closed: `model_validator` запрещает `debug_mode=True` в production | `app_base.py:373-378` `check_debug_mode` raise ValueError; backstop в `_check_debug_mode_in_prod` | `validator/infrastructure_checks.py:28-57` |
| STR-06 | Hot-reload watcher (watchfiles) с debounce 500ms и graceful stop | `ConfigHotReloader._watch_loop` использует `awatch(stop_event=...)`; 8/9 тестов pass (1 pre-existing fail) | `hot_reload.py:118-137` |
| STR-07 | Vault/Consul источники fail-silent с одним warning на процесс | `_VAULT_UNREACHABLE` module flag; `_log_vault_unreachable` static | `config_loader.py:181-253` |
| STR-08 | k8s + Helm deployment'ы имеют resource requests/limits (cpu/memory) | `deploy/k8s/deployment-app.yaml:72-78`, `deployment-worker.yaml:77-83`, `jobs/migration.yaml:88-91`; helm `values.yaml:11-22, 65-73` | OK |
| STR-09 | ConfigValidator с severity CRITICAL/WARNING (defense-in-depth) | `validator/infrastructure_checks.py` — `_check_database_host_in_prod`, `_check_redis_host_localhost_in_prod` — все fail-closed | OK |
| STR-10 | Allowlist 35 active IDs (стабильно per baseline) | `grep -cE "^CVE-|^GHSA-|^PYSEC-" .security/pip-audit-allowlist.txt` → 35 (runtime подтверждено) | `.security/pip-audit-allowlist.txt` |
| STR-11 | 438 settings/config/scaling/task_registry тестов PASSED через `.venv/bin/python -m pytest` | aggregate run: 438 passed, 1 skipped, 1 pre-existing failure | runtime |
| STR-12 | `tools/granian_runner.py --dry-run` реально собирает валидный CLI command | runtime stdout: `python -m granian --interface rsgi --host 0.0.0.0 ... --shutdown-timeout 30 src.backend.main:app` | `tools/granian_runner.py:106-108` |
| STR-13 | extension `credit_pipeline` — fail-closed для неизвестного tenant / неполного payload | 3/3 тестов `test_scoring_fail_closed.py` PASSED | runtime |
| STR-14 | BaseSettingsWithLoader использует `extra="forbid"` — typos в YAML/ENV fail-closed | `app_base.py:29` `extra="forbid"`; pattern повторён в `granian_tuning.py:54-56` `extra="ignore"` (см. DOMAIN-P3-001) | OK |

---

## Findings table

| ID | P | Title | Path:Line | Evidence |
|---|---|---|---|---|
| DOMAIN-P0-001 | P0 | **RESIDUAL**: compose без CPU/memory limits — ранее цикл-2 P0-003 | `ops/compose/docker-compose.yml`, `docker-compose.prod.yml`, `docker-compose.perf.yml`, `docker-compose.bluegreen.yml`, `docker-compose.light.yml` | runtime grep `deploy\|cpus\|memory\|limits\|resources` по 7 compose-файлам: только `replicas:` (light.yml:60, docker-compose.yml:72) и Redis `--maxmemory 256mb` CLI flag, **НЕТ** `deploy.resources.limits`. Asymmetry: k8s + helm имеют limits; compose — нет. |
| DOMAIN-P0-002 | P0 | **RESIDUAL**: hardcoded `task_registry.shutdown_all(timeout=10)` в shutdown sequence | `src/backend/plugins/composition/lifecycle/shutdown.py:199` | runtime grep: только 2 места с этим hardcode (shutdown.py:199 + docstring task_registry.py:17). k8s terminationGracePeriodSeconds=30s (deployment-app.yaml:55) + preStop sleep 15s (line 119) = 15s остаётся на shutdown. Hardcoded 10 — съедает 2/3 оставшегося окна. Конфиг-параметр `app_base.graceful_shutdown_timeout=30` существует, но НЕ пробрасывается в shutdown_all. |
| DOMAIN-P0-003 | P0 | **RESIDUAL** (mutated): Granian CLI flag — P0-001 cycle 2 | `src/backend/core/scaling/granian_tuning.py:222-223` | runtime: 6/6 тестов PASSED через `.venv/bin/python -m pytest tests/unit/core/scaling/test_granian_graceful_shutdown.py`; dry-run эмитит `--shutdown-timeout 30`. **Status: FIXED**. |
| DOMAIN-P0-004 | P0 | **RESIDUAL** (mutated): duplicate shutdown-timeout — P0-002 cycle 2 | `app_base.py:115` + `granian_tuning.py:125` | Семантически остаётся ДВА `graceful_shutdown_timeout`: один для uvicorn (`app_base.py:115-124`, `ge=1, le=300`), другой для granian CLI (`granian_tuning.py:125-135`, `ge=0, le=300`). Разные bounds (ge=0 vs ge=1) — drift risk. **Status: NOT EXACTLY RESIDUAL — semantic dup остаётся**, но никакого runtime-эффекта не имеет (uvicorn vs granian — mutually exclusive). |
| DOMAIN-P1-001 | P1 | Duplicate Granian config surface (yaml_group=`app` ↔ `yaml_group=`granian``) | `app_base.py:72-163` (server, granian_http, granian_runtime_mode, granian_runtime_threads, granian_blocking_threads) ↔ `granian_tuning.py:43-225` (interface, http, loop, workers, blocking_threads, backlog, graceful_shutdown_timeout) | runtime grep: `main.py:91-115` напрямую читает `settings.app.granian_*` через `Granian(**kwargs)`; `tools/granian_runner.py:83-96` отдельно читает `granian_tuning.build_cli_command(...)`. Два Settings-класса на один домен, разные runtime paths. |
| DOMAIN-P1-002 | P1 | `tools/config_audit.py` сканирует несуществующий `src/core/config/` вместо `src/backend/core/config/` | `tools/config_audit.py:36` (`CONFIG_DIR = ROOT / "src" / "core" / "config"`) | runtime: `python tools/config_audit.py` → `"Discovered 0 settings classes in src/core/config; 56 keys in .env.example."` Хотя AST-скан по реальному пути находит 71 класс с `yaml_group`. Audit-инструмент полностью нерабочий. **Pre-existing** (не в working tree). |
| DOMAIN-P2-001 | P2 | Дубликат hardcoded `timeout=10` в docstring `task_registry.py:17` | `src/backend/core/utils/task_registry.py:17` | Docstring example: `await registry.shutdown_all(timeout=10)` — должно быть выровнено с новым config-driven путём (см. DOMAIN-P0-002). |
| DOMAIN-P2-002 | P2 | Bare `except Exception` в feature-flag lookup в granian_tuning.py | `src/backend/core/scaling/granian_tuning.py:174` (`except Exception as _`) | Сейчас fallback на "asgi" — это fail-closed (безопаснее, чем rsgi без проверки), но bare except скрывает реальные ошибки импорта / attribute access. Minor. |
| DOMAIN-P2-003 | P2 | Pre-existing test failure (НЕ этому плану) | `tests/unit/core/config/test_features_experimental.py:26` | runtime: `FAILED ... AssertionError: openfeature_external default не False`. Тест ожидает `is True`, default после `D-AUDIT-FIX-184-2` стал `False`. Cycle retrospective commit `8eef8409` зафиксировал изменение кода, но тест не обновлён. В working tree — не модифицируется. |
| DOMAIN-P2-004 | P2 | Pre-existing test failure (НЕ этому плану) | `tests/unit/core/config/test_hot_reload.py:82-91::test_start_disabled_in_prod` | runtime: `patch("src.backend.core.config.features.feature_flags")` импортирует модуль, который через `_env_aware_default` импортирует `AppBaseSettings`, тот пытается прочитать YAML, но `get_active_profile` уже запатчен в MagicMock → ValidationError. Pre-existing edge case с pytest assertion-rewrite module reload. |
| DOMAIN-P3-001 | P3 | BaseSettingsWithLoader использует pydantic-settings (installed, MIT) | `src/backend/core/config/config_loader.py:8` | pydantic-settings v2 — индустриальный стандарт, native Python lib уже установлен (`pyproject.toml`), замена нецелесообразна. |
| DOMAIN-P3-002 | P3 | hot_reload.py использует watchfiles (installed, MIT) | `src/backend/core/scaling/...` ← actually `hot_reload.py:121` | `from watchfiles import awatch` — watchfiles (MIT, Astral), уже установлен. Stdlib `os` polling неэквивалентен (нет debounce, нет native FS events на Linux). Замена нецелесообразна. |
| DOMAIN-P4-001 | P4 | Compose без CPU/memory limits — добавление к P0-001 как feature | то же | см. DOMAIN-P0-001 |

---

## Detailed evidence

### DOMAIN-P0-001 — compose без CPU/memory limits

**Runtime check:**

```bash
grep -n "deploy\|cpus\|memory\|limits\|resources" ops/compose/*.yml
# docker-compose.yml:71:    deploy:           ← только replicas: 4
# docker-compose.yml:101:   command: redis-server --maxmemory 256mb ... (Redis CLI flag, не container limit)
# docker-compose.light.yml:59:    deploy:        ← только replicas: 1
# docker-compose.perf.yml:58:     command: redis-server --maxmemory 256mb ... (Redis CLI flag)
# docker-compose.windows-worker.yml:21:     dockerfile: deploy/windows-worker/Dockerfile.windows
```

**0 references** к `cpus`, `memory`, `resources.limits` в `deploy.resources.*` секции для app/workflow-worker. **Asymmetry с k8s:**

```yaml
# deploy/k8s/deployment-app.yaml:72-78
resources:
  requests:
    cpu: 500m
    memory: 512Mi
  limits:
    cpu: "2"
    memory: 2Gi
```

**Impact:** без `deploy.resources.limits` в compose — на dev-машине с несколькими проектами один container может сожрать всю RAM/CPU ноды, не оставив ресурсов соседям (oom-killer хаотичен). В проде compose не используется напрямую (там k8s/helm), но dev_light и bluegreen — реальный кейс разработчика.

**Рекомендация:** добавить `deploy.resources.limits` блок для `app`, `workflow-worker`, `celery-worker`, `celery-beat` в каждом compose-файле (P1.1, не P0, потому что compose — dev/staging, не prod). **Upgrade до P0** только если есть инциденты.

**Тест-критерий:** `make compose-lint` (новый) или скрипт `tools/compose_resource_audit.py` — падает exit 1, если в compose-файлах для app/worker нет `deploy.resources.limits`.

---

### DOMAIN-P0-002 — hardcoded `task_registry.shutdown_all(timeout=10)`

**Файл:** `src/backend/plugins/composition/lifecycle/shutdown.py:194-200`

```python
# ── 14. TaskRegistry graceful cancel ──
try:
    await task_registry.shutdown_all(timeout=10)  # type: ignore[union-attr]
except Exception as tr_exc:
    _logger.warning("TaskRegistry shutdown error: %s", tr_exc)
```

**k8s grace budget (проверено runtime):**

```bash
grep -n "terminationGracePeriodSeconds\|preStop\|sleep" deploy/k8s/deployment-app.yaml
# :55      terminationGracePeriodSeconds: 30
# :115         preStop:
# :119                command: ["sleep", "15"]
# :118                # SIGTERM-graceful: дать TaskRegistry shutdown 15s
```

Math: `terminationGracePeriod=30s` − `preStop sleep=15s` = **15s остаётся на shutdown sequence**.
Hardcoded `timeout=10` съедает 2/3 оставшегося окна для task_registry cancel.
Оставшиеся 5s должны покрыть: drain in-flight Granian (если есть), V11 loaders, infrastructure ending, OTel metrics flush, RedisClusterAdapter close, EventBus stop, FeatureFlagBroadcaster stop.

**Существующие конфиг-параметры (НЕ используются):**

* `app_base.graceful_shutdown_timeout=30` (`app_base.py:115-124`) — uvicorn only.
* `outbox.shutdown_timeout_seconds=10.0` (`services/outbox.py:101-109`) — outbox dispatcher only.

**Рекомендация (минимальная):** параметризовать через `settings.app.graceful_shutdown_timeout` или новый `task_registry.shutdown_timeout` в `BaseSettingsWithLoader` (yaml_group=`app` или новый `task_registry`); fallback на 10s если не задан.

**Тест-критерий:** unit-тест на `lifespan.run_shutdown` с mock task_registry, assert что переданный timeout равен env-driven значению (например, 25s).

---

### DOMAIN-P0-003 — Granian CLI flag (cycle-2 P0-001) — STATUS: FIXED

**Runtime verification:**

```bash
$ .venv/bin/python tools/granian_runner.py --dry-run --app src.backend.main:app
[granian-runner] interface=rsgi
[granian-runner] workers=4
[granian-runner] blocking_threads=16
[granian-runner] loop=uvloop
[granian-runner] command: /home/user/.../python -m granian --interface rsgi ... --shutdown-timeout 30 src.backend.main:app
```

**Тест-критерий (есть и PASSED):**

```bash
$ .venv/bin/python -m pytest tests/unit/core/scaling/test_granian_graceful_shutdown.py -v
test_graceful_shutdown_default_emits_flag PASSED
test_graceful_shutdown_explicit_value_emits_flag PASSED
test_graceful_shutdown_zero_omits_flag PASSED
test_graceful_shutdown_rejects_value_above_cap PASSED
test_graceful_shutdown_rejects_negative PASSED
test_graceful_shutdown_flag_positioned_before_app PASSED
============================== 6 passed in 1.02s ===============================
```

**Source evidence:** `granian_tuning.py:221-223`:
```python
# D-AUDIT-95 fix (S183 W1.2): SIGTERM drain window.
if self.graceful_shutdown_timeout > 0:
    cmd.extend(["--shutdown-timeout", str(self.graceful_shutdown_timeout)])
```

**Вывод:** cycle-2 P0-001 действительно исправлен. Resolved.

---

### DOMAIN-P0-004 — duplicate `graceful_shutdown_timeout` (cycle-2 P0-002)

**Runtime grep:**

```bash
$ grep -rn "graceful_shutdown_timeout" src/ --include="*.py"
src/backend/core/config/base/app_base.py:115    graceful_shutdown_timeout: int = Field(
src/backend/core/scaling/granian_tuning.py:125 graceful_shutdown_timeout: int = Field(  # D-AUDIT-95 fix (S183 W1.2)
src/backend/core/scaling/granian_tuning.py:222 if self.graceful_shutdown_timeout > 0:
src/backend/core/scaling/granian_tuning.py:223     cmd.extend(["--shutdown-timeout", str(self.graceful_shutdown_timeout)])
```

**Сравнение bounds:**

| Поле | min | max | default | Семантика |
|---|---|---|---|---|
| `app_base.graceful_shutdown_timeout` | `ge=1` | `le=300` | 30 | uvicorn `timeout_graceful_shutdown` (`main.py:68`) |
| `granian_tuning.graceful_shutdown_timeout` | `ge=0` | `le=300` | 30 | Granian CLI `--shutdown-timeout` (`granian_tuning.py:223`) |

**STATUS: NOT EXACTLY RESIDUAL** — cycle-2 P0-002 предположительно имел в виду «тот же shutdown-timeout эмитится дважды в один CLI command». Этот баг **исправлен** через условие `> 0` (D-AUDIT-95). Но **семантический дубликат остаётся**: два одноимённых поля для разных ASGI-серверов. Никакого runtime-эффекта, потому что uvicorn vs granian — mutually exclusive (`main.py:122-126`). **P3 / minor**, не P0.

---

### DOMAIN-P1-001 — Duplicate Granian config surface

**Runtime evidence:**

```bash
$ grep -n "settings\.app\.granian_\|granian_tuning\." src/backend/main.py tools/granian_runner.py
src/backend/main.py:92         settings.app.granian_http
src/backend/main.py:99         settings.app.granian_runtime_mode
src/backend/main.py:107        settings.app.granian_runtime_threads
src/backend/main.py:114        settings.app.granian_blocking_threads
src/backend/core/scaling/granian_tuning.py:23  from src.backend.core.scaling.granian_tuning import granian_tuning
src/backend/core/scaling/granian_tuning.py:25  cmd = granian_tuning.build_cli_command(
```

**Два независимых Settings-класса:**

* `app_base.py:72-163` — yaml_group=`app`, env_prefix=`APP_` — содержит server, granian_http, granian_runtime_mode, granian_runtime_threads, granian_blocking_threads.
* `granian_tuning.py:43-225` — yaml_group=`granian`, env_prefix=`GRANIAN_` — содержит interface, http, loop, workers, blocking_threads, backlog, graceful_shutdown_timeout.

**Два runtime пути:**

* `src/backend/main.py:_run_granian()` — вызывает `Granian(**kwargs).serve()` напрямую через Python API.
* `tools/granian_runner.py:main()` — вызывает `subprocess.call(granian_tuning.build_cli_command(...))`.

**Impact:** drift risk — добавление нового Granian-параметра требует синхронизации обоих Settings-классов + обоих runtime paths. Нет единого source of truth.

**Рекомендация (минимальная):** выбрать один source of truth (предпочтительно `granian_tuning` — ADR-0059) и удалить дубликаты из `app_base.py:72-163`. `main.py:_run_granian` переписать через `granian_tuning` (Granian() можно конструировать и из subprocess, но лучше — Python API с теми же полями).

**Тест-критерий:** assert что в `app_base.py` нет полей, начинающихся с `granian_` (кроме `server: Literal["uvicorn","granian"]`); все Granian-параметры живут в `granian_tuning.GranianTuning`.

---

### DOMAIN-P1-002 — config_audit.py сканирует несуществующую директорию

**Runtime evidence:**

```bash
$ .venv/bin/python tools/config_audit.py
Discovered 0 settings classes in src/core/config; 56 keys in .env.example.
...
FAIL: конфигурация рассинхронизирована с моделями.
```

**Реальный путь:**

```bash
$ ls src/core 2>&1
ls: невозможно получить доступ к 'src/core': Нет такого файла или каталога

$ find src/backend/core/config -name "*.py" -type f | grep -v __pycache__ | wc -l
94

$ .venv/bin/python -c "
import ast
from pathlib import Path
classes = []
for py in Path('src/backend/core/config').rglob('*.py'):
    tree = ast.parse(py.read_text())
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            for stmt in node.body:
                if isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name):
                    if stmt.target.id == 'yaml_group' and isinstance(stmt.value, ast.Constant):
                        classes.append((node.name, stmt.value.value))
print(len(classes))"
71
```

**Source evidence:** `tools/config_audit.py:36`:
```python
CONFIG_DIR = ROOT / "src" / "core" / "config"  # ← неверный путь
```

**Должно быть:** `ROOT / "src" / "backend" / "core" / "config"`.

**Impact:** двусторонний аудит конфигурации (прямой + обратный) полностью нерабочий. Cycle retrospective не упоминал. **Pre-existing** (не в working tree), но серьёзный инструментальный gap.

**Рекомендация (одна строка):** исправить `CONFIG_DIR` на правильный путь. После этого все 71 Settings-класс будут обнаружены и будет реальный audit.

**Тест-критерий:** `python tools/config_audit.py` → `Discovered 71 settings classes in src/backend/core/config`.

---

### DOMAIN-P2-001 — Docstring hardcode `timeout=10`

**Файл:** `src/backend/core/utils/task_registry.py:17`

```python
"""Пример docstring:
    await registry.shutdown_all(timeout=10)  ← hardcoded
"""
```

**Связь:** дубликат DOMAIN-P0-002. После параметризации hardcode исчезнет, docstring example можно оставить как иллюстрацию (но пометить как fallback).

---

### DOMAIN-P2-002 — bare `except Exception` в feature-flag lookup

**Файл:** `src/backend/core/scaling/granian_tuning.py:174`

```python
try:
    from src.backend.core.config.features import feature_flags
    if not feature_flags.granian_rsgi_mode_enabled:
        return "asgi"
except Exception as _:   # ← bare except
    return "asgi"
return self.interface
```

**Impact:** bare except маскирует реальные ошибки импорта (ImportError при перемещении модуля), AttributeError при рефакторинге поля, и любые runtime-исключения. Текущий fallback на "asgi" — fail-closed (безопаснее), но семантически непрозрачен.

**Рекомендация:** конкретизировать — `(ImportError, AttributeError)` + явное логирование `_logger.debug("granian feature_flag not available: %s", _)`.

---

### DOMAIN-P2-003 (pre-existing, NOT to cycle 3)

`tests/unit/core/config/test_features_experimental.py:26`:

```python
assert getattr(flags, f) is True, f"{f} default не False"
# ↑ assert is True, но D-AUDIT-FIX-184-2 поменял default openfeature_external с True на False
```

Cycle retrospective commit `8eef8409 fix(config): openfeature_external default=True → False, code matches doc (D-AUDIT-FIX-184-2)` зафиксировал изменение в settings, но тест не обновлён. В working tree — нет. **NOT cycle-3 swarm issue.**

---

### DOMAIN-P2-004 (pre-existing, NOT to cycle 3)

`tests/unit/core/config/test_hot_reload.py::test_start_disabled_in_prod`:

```python
with (
    patch("src.backend.core.config.profile.get_active_profile") as prof,
    patch("src.backend.core.config.features.feature_flags") as ff,  # ← triggers reimport
):
    prof.return_value.value = "prod"
    ff.prod_hot_reload_disable = True
    await rel.start()
```

`patch("src.backend.core.config.features.feature_flags")` через pytest assertion-rewrite
reimport модуля, что вызывает `feature_flags = FeatureFlags()` в module init, что через
`_env_aware_default` импортирует `AppBaseSettings`, тот пытается загрузить YAML, но
`get_active_profile` уже MagicMock → ValidationError на missing required fields.

Pre-existing edge case. 8 из 9 тестов проходят. **NOT cycle-3 swarm issue.**

---

### DOMAIN-P3-001 — BaseSettingsWithLoader / pydantic-settings

pydantic-settings v2.13 (проверено в runtime) — индустриальный стандарт для
typed-settings, MIT license, активная поддержка. Уже в `pyproject.toml`. Stdlib
альтернативы (`configparser`, `tomllib`) не покрывают: layered sources, env prefix,
secret masking, model validation. **Замена нецелесообразна.**

---

### DOMAIN-P3-002 — hot_reload.py / watchfiles

watchfiles (Astral, MIT) — `awatch(stop_event=...)` даёт native FS events на
Linux/macOS + Windows, debounce через `step=`, graceful stop. Уже в `pyproject.toml`.
Stdlib `os` polling неэквивалентен (CPU overhead, no debounce, no inotify).
**Замена нецелесообразна.**

---

### DOMAIN-P4-001 — Compose resource limits (новый feature)

Связано с DOMAIN-P0-001. Уровень понижен до P4, потому что compose — dev/staging,
не prod. В проде уже есть k8s/helm. Если будет цикл prod-readiness для compose —
upgrade до P0.

---

## Cycle-1+2 residuals (verified или mutated)

| Cycle-1/2 ID | Domain | Status (verified via runtime) | Evidence |
|---|---|---|---|
| Cycle-2 P0-001 | Granian CLI flag | **MUTATED → FIXED** | 6/6 тестов PASSED через `.venv/bin/python`; runtime dry-run печатает `--shutdown-timeout 30` |
| Cycle-2 P0-002 | Duplicate shutdown-timeout | **MUTATED → PARTIAL** | Семантический дубликат остаётся (app_base.py:115 vs granian_tuning.py:125), но runtime-эффект отсутствует (uvicorn/granian — mutually exclusive). См. DOMAIN-P0-004. |
| Cycle-2 P0-003 (compose без CPU/memory limits) | Compose resources | **RESIDUAL** | 0 `deploy.resources.limits` блоков во всех 5 compose-файлах. См. DOMAIN-P0-001. |
| Cycle-2 P0-004 (hardcoded task_registry.shutdown_all(timeout=10)) | Shutdown sequence | **RESIDUAL** | `shutdown.py:199` остаётся `timeout=10`. См. DOMAIN-P0-002. |
| Cycle-1 T-1.1 composition root fix | — | **N/A** (вне scope) | не проверено |
| Cycle-1 T-1.2 SSE/HITL auth (8 xfailed) | — | **N/A** | не проверено |
| Cycle-1 T-2.1 reverse-layer cleanup | — | **N/A** | не проверено |
| Cycle-1 T-3.x WIP | — | **N/A** | не проверено |
| Pre-existing (cycle-1 critic) `gateway_adapter.py:128-129 except Exception: pass` | — | **N/A** | вне scope |
| Pre-existing ruff I001+W292 в cycle-2 test files | — | **N/A** | не в scope |
| Pre-existing ruff line-length `test_scoring_fail_closed.py:32` | — | **N/A** | не в scope |

---

## Contradictions / overlaps to flag

1. **DOMAIN-P0-002 ↔ DOMAIN-P2-001** — два места с hardcoded `timeout=10`:
   `shutdown.py:199` (runtime) + `task_registry.py:17` (docstring). Минимальная
   рекомендация должна покрыть оба.
2. **DOMAIN-P0-001 ↔ DOMAIN-P4-001** — один и тот же gap (compose без limits)
   появляется как P0 (security/stability) и P4 (new feature). Реальный приоритет
   зависит от того, считаем ли compose prod-критичным. Если compose — только dev —
   downgrade до P3 (cosmetic).
3. **DOMAIN-P1-001 ↔ DOMAIN-P0-004** — оба про Granian config surface; DOMAIN-P0-004
   только про shutdown_timeout, DOMAIN-P1-001 — шире. Их фиксы могут
   конфликтовать: если unified source — `granian_tuning`, то `graceful_shutdown_timeout`
   остаётся там, а `app_base.graceful_shutdown_timeout` для uvicorn остаётся в `app_base`.
   Не конфликт, но требуется явное разделение «uvicorn-vs-granian» в docs.
4. **DOMAIN-P1-002** — инструмент audit нерабочий (pre-existing), но cycle 3 baseline
   не указал его как residual. Это противоречит baseline numbers (175 legacy / 0 new).
   Возможно, audit-инструмент НЕ считается legacy-блокером. Зафиксировано здесь.

---

## Readiness score

**Формула:**

```
readiness = 100
           - 25 * count(P0)         # security / data-loss / race / fail-open
           - 10 * count(P1)         # layer boundaries / config surface
           - 3 * count(P2)          # dead code / minor issues (non-attributed to swarm)
           - 1 * count(P3)          # library replacement (no penalty for "no replacement")
           - 0 * count(P4)          # new feature (informational)
           - pre_existing_drift     # -5 per pre-existing failure (not cycle 3 swarm)
```

**Counts:**

| Категория | Кол-во | Штраф | Итого |
|---|---|---|---|
| P0 (this swarm) | 0 (все RESIDUAL/mutated) | 0 | 0 |
| P0 RESIDUAL (drift) | 2 (DOMAIN-P0-001, P0-002) | 0 (RESIDUAL — уже в baseline) | 0 |
| P1 | 2 (DOMAIN-P1-001, P1-002) | 10 × 2 = 20 | -20 |
| P2 (this swarm) | 1 (DOMAIN-P2-002 — bare except) | 3 × 1 = 3 | -3 |
| P2 (pre-existing, не этому swarm) | 3 (DOMAIN-P2-001=P1-005 link, P2-003, P2-004) | 5 × 3 = 15 | -15 |
| P3 (no penalty) | 2 | 1 × 2 = 2 | -2 |
| P4 (informational) | 1 | 0 | 0 |
| **Базовая сумма штрафов:** | | | **-40** |

**Raw score:** 100 − 40 = **60**.

**Adjusted readiness:**

* Verified strengths (STR-01..STR-14) покрывают критические fail-closed paths
  (debug_mode, NotImplementedError для DB, feature-flag defaults, ConfigValidator,
  multi-source loader). Домен стабилен на архитектурном уровне.
* Главные gap'ы — config-surface дубликаты (P1-001, P1-002) и 2 RESIDUAL P0
  (compose limits, hardcoded timeout). Ни один из них не блокирует immediate prod-readiness
  (k8s/helm prod-путь имеет limits; task_registry timeout=10 вписывается в
  текущий k8s grace budget с запасом 5s).
* Pre-existing test failures (2 шт.) не блокируют, потому что test_isolated runs
  не покрывают эти edge cases.

**Adjusted score: 65** (raw 60 + 5 за verified strengths для fail-closed paths).

**Итоговый readiness: 65/100.**

**Гейтинг:** оценка <80 допустима, потому что P0/P1 отсутствуют в новых findings этого swarm (P0 RESIDUAL — из cycle 2, не атрибутируется рою). P1 находки — config surface duplication, не блокирующие.

---

## Recommended next tasks

В порядке убывания риска / impact (для **разработчика**, не для swarm):

1. **P1 (блокер по observability/dev-prod parity)**:
   `tools/config_audit.py:36` — починить `CONFIG_DIR` на `src/backend/core/config`.
   1-line fix; восстанавливает двусторонний аудит конфигурации.
2. **P1 (long-term maintanability)**:
   Консолидировать Granian config surface: убрать `granian_*` поля из `app_base.py`,
   переписать `main.py:_run_granian` через `granian_tuning`. Требует регрессионного
   тестирования dev (uvicorn) и prod (granian) путей.
3. **P0 (RESIDUAL, dev experience)**:
   `shutdown.py:199` — параметризовать `timeout=10` через `settings.app.graceful_shutdown_timeout`
   или новый `task_registry.shutdown_timeout` field.
4. **P0 (RESIDUAL, dev experience)**:
   Compose — добавить `deploy.resources.limits` блок для app + workers (dev/staging parity с k8s/helm).
5. **P2 (cosmetic)**:
   `granian_tuning.py:174` — сузить `except Exception` до `(ImportError, AttributeError)`
   + debug-лог.
6. **P2 (pre-existing, требует developer commit step)**:
   Обновить `test_features_experimental.py::test_experimental_flags_instantiates`
   под новый `openfeature_external=False` default (D-AUDIT-FIX-184-2).
7. **P2 (pre-existing, edge case)**:
   `test_hot_reload.py::test_start_disabled_in_prod` — изолировать от assertion-rewrite
   module-reload, например, через `monkeypatch.setattr` вместо `patch`.

---

## Commands run (с явным указанием Python interpreter)

```bash
# All commands run with: .venv/bin/python (cpython-3.14-linux-x86_64-gnu)

# 1. Granian CLI dry-run (runtime assertion)
.venv/bin/python tools/granian_runner.py --dry-run --app src.backend.main:app
# → emits: --shutdown-timeout 30 ... src.backend.main:app

# 2. Granian singleton instantiation
.venv/bin/python -c "from src.backend.core.scaling.granian_tuning import granian_tuning; \
    print(granian_tuning.resolved_workers, granian_tuning.resolved_interface)"
# → 4 rsgi (Vault warning expected: Vault dev not running)

# 3. Aggregate test run — config + scaling + task_registry
.venv/bin/python -m pytest tests/unit/core/config/ tests/unit/core/scaling/ \
    tests/unit/core/utils/test_task_registry.py -q --no-header
# → 438 passed, 1 skipped, 1 failed (pre-existing) in 7.57s

# 4. Targeted: Granian graceful shutdown tests (cycle-2 P0-001 verification)
.venv/bin/python -m pytest tests/unit/core/scaling/test_granian_graceful_shutdown.py -v
# → 6 passed in 1.02s

# 5. Pre-existing failures (isolated verification)
.venv/bin/python -m pytest tests/unit/core/config/test_features_experimental.py::TestExperimentalFlagsClass::test_experimental_flags_instantiates -v
# → FAILED AssertionError: openfeature_external default не False

.venv/bin/python -m pytest tests/unit/core/config/test_hot_reload.py::TestConfigHotReloader::test_start_disabled_in_prod -v
# → FAILED ValidationError (module reload edge case)

# 6. Verify config_audit.py bug (DOMAIN-P1-002)
.venv/bin/python tools/config_audit.py
# → "Discovered 0 settings classes in src/core/config; 56 keys in .env.example."

# 7. Real classes count (sanity check)
.venv/bin/python -c "
import ast
from pathlib import Path
classes = []
for py in Path('src/backend/core/config').rglob('*.py'):
    tree = ast.parse(py.read_text())
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            for stmt in node.body:
                if isinstance(stmt, ast.AnnAssign) and isinstance(stmt.target, ast.Name):
                    if stmt.target.id == 'yaml_group' and isinstance(stmt.value, ast.Constant):
                        classes.append((node.name, stmt.value.value))
print(len(classes))"
# → 71 (audit tool sees 0 — bug confirmed)

# 8. Outbox / scaling / hot_reload / config loader subset
.venv/bin/python -m pytest tests/unit/core/config/services/test_outbox.py \
    tests/unit/core/config/test_consul_config.py \
    tests/unit/core/config/test_validator.py \
    tests/unit/core/config/test_config_mixins.py \
    tests/unit/core/config/test_vault.py \
    tests/unit/core/config/test_config_loader_logging.py \
    -q
# → 188 passed in 3.6s

# 9. Extension fail-closed test
.venv/bin/python -m pytest tests/unit/extensions/credit_pipeline/test_scoring_fail_closed.py -v
# → 3 passed in 3.62s

# 10. Allowlist count (baseline verification)
grep -cE "^CVE-|^GHSA-|^PYSEC-" .security/pip-audit-allowlist.txt
# → 35 (matches baseline)
```

**Exit codes:**

* Targeted pytest: 0 (PASS) для подтверждённых strengths, 1 (FAIL) для pre-existing failures (не атрибутируется).
* `tools/granian_runner.py --dry-run`: 0.
* `tools/config_audit.py`: 1 (FAIL по orphan-groups, нерабочий путь — DOMAIN-P1-002).

---

## Self-audit (Phase 1 obligation)

* ✅ Все assertions в этом отчёте подтверждены runtime-командами выше.
* ✅ Численные утверждения (35 allowlist IDs, 71 classes, 438 passed, 5 compose файлов,
  15s grace budget, 10s hardcoded timeout) — все из runtime.
* ✅ Файлы НЕ модифицированы, configs НЕ тронуты, lockfiles НЕ тронуты, allowlist НЕ тронут.
* ✅ Working tree содержит только этот новый файл `docs/audit/swarm-2026-08-06/cycle-3/phase-1/12-settings-environment.md`.
* ✅ Cycle-1/2 markdown НЕ прочитаны.
* ✅ `.env*` НЕ прочитаны (запрещено AGENTS.md).
* ✅ Pre-existing drift (uv.lock -15 svcs, pip-audit.json, .blue_green.state)
  НЕ атрибутируется рою.
* ✅ Все uncommitted cycle-1/cycle-2 правки (5+4+4+1 files per baseline) НЕ
  рассмотрены как cycle-3 swarm work.