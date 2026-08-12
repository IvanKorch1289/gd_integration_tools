# Cycle 3 — Phase 3 — Минимальный план доработки

- **Дата:** 2026-08-06
- **HEAD:** `7f3d94a388199c136bd7b90fa73d3b5a1217d4f7`
- **Автор:** Phase 3 architect (read-only, никаких правок source/configs/lockfiles/allowlist)
- **Источник:** только `docs/audit/swarm-2026-08-06/cycle-3/BASELINE.md` и
  `docs/audit/swarm-2026-08-06/cycle-3/PHASE-2-SUMMARY.md`. Source-код,
  `CLAUDE.md`, `PLAN.md`, `KNOWN_ISSUES.md`, cycle-1/cycle-2 markdown — НЕ читались.
- **Baseline-инварианты (из BASELINE.md):**
  - Layer checker: `python tools/check_layers.py --root src` → 175 legacy / 0 new (2274 файлов).
  - Security allowlist: `grep -cE "^CVE-|^GHSA-|^PYSEC-" .security/pip-audit-allowlist.txt` → 35 active IDs (стабильно).
  - Docstring gate: `make check-docstrings MAX_ALLOWED=0` → 0 missing (838 файлов).
  - Runtime: **только** `.venv/bin/python -m pytest` (system Python лишён пакетов; reviewer cycle 2 ошибся).
  - uv.lock churn не растёт (-15 svcs — pre-existing drift, не атрибутируется рою).
- **Pre-existing drift (НЕ трогать):** `M uv.lock` (-15 svcs), `?? pip-audit.json`,
  `?? .blue_green.state`, `tools/blue_green.sh`, `test_blue_green_switch.py`,
  `.blue_green.state`. Pre-existing residual `services/ai/gateway_adapter.py:128-129`
  `except Exception: pass` — не трогать. 5 uncommitted cycle-1 правок
  (T-0.1, T-1.4, T-1.5, T-3.1) + 3 uncommitted cycle-2 правки (T-W1-01, T-W1-05,
  T-W1-08) — не переписывать. 5 test-masking issues из cycle 2 PHASE-2 §5.3
  подтверждены в cycle 3 (TM-1..TM-5, см. PHASE-2 §1.4). 15 contradictions
  C-1..C-15 (см. PHASE-2 §5) — учтены при приоритизации.

> **Соглашения.** Глобальный task ID: `C3-NN` (Cycle-3 номер). Docstring marker:
> `# cycle-3/D-AUDIT-NN` (в шапке модуля или в docstring функции/класса). Все
> runtime-проверки — только `.venv/bin/python -m pytest <path>`. Минимальный diff
> — минимум строк для устранения root cause; никакого refactoring «на потом».
> Ponytail mode активен (YAGNI / shortest working diff).

---

## 0. Сводка для родителя

| Метрика | Значение |
|---|---|
| Всего задач | **12** (Wave 0: 1 + Wave 1: 6 + Wave 2: 2 + Wave 3: 1 + Wave 4: 1 + Wave N: 1) |
| Параллельных групп | **4** (PG-1, PG-2, PG-3, PG-4 — см. раздел 7) |
| Top dependencies (chain) | T-02 (pyproject.toml) → T-07 (test-infra conftest) → T-03 (test-masking); T-05 (composition root) → T-01 (workflow DSL) |
| Deferred в cycle 4+ | 1 задача (T-12) |
| Baseline-инварианты | 175/0, allowlist 35, uv.lock без изменений — зафиксированы в каждой DoD |

---

## 1. Wave 0 — Developer preflight (1 задача)

> Цель: подтвердить, что 14 modified + 8 untracked файлов (cycle-1 + cycle-2 +
> drift) не задевают плановое ядро и дать разработчику явный commit step **до**
> старта роя. Без этого нельзя гарантировать, что failure attribution
> корректна (см. PHASE-2 C-11).

### T-01 — Developer commit step (wave 0)

- **Global task ID:** `C3-01`
- **Source finding IDs:** BASELINE.md L5, L32-39; PHASE-2 C-11
- **Приоритет:** P0 (блокер для всей роевой работы, см. C-11)
- **Домены:** cross-domain (developer-only)
- **Точные пути файлов:** 5 uncommitted cycle-1 (T-0.1, T-1.4, T-1.5, T-3.1) +
  3 uncommitted cycle-2 (T-W1-01, T-W1-05, T-W1-08) + `tools/cycle-1-preflight.sh`
  + audit docs. **Pre-existing drift** (`uv.lock`, `pip-audit.json`,
  `.blue_green.state`, `tools/blue_green.sh`, `test_blue_green_switch.py`) —
  оставить untracked/as-is.
- **Минимальный diff:** 0 LOC. Действие: `git add` + `git commit` для cycle-1/2
  правок одной волной (например `chore: commit cycle-1/2 preflight uncommitted`)
  с pre-existing drift **исключённым** через `git status` visibility check.
- **Зависимости:** нет
- **Параллельность:** serial (blocker для всех остальных задач)
- **LOC range:** 0 (commit-only)
- **Критерий "готово":**
  - `.venv/bin/python -m pytest tests/unit -x --co -q 2>&1 | head -20` → exit 0
    (collection без error, чтобы подтвердить, что uncommitted правки не ломают import graph).
  - `git status --short` показывает только pre-existing drift
    (`M uv.lock`, `?? pip-audit.json`, `?? .blue_green.state`).
  - `python tools/check_layers.py --root src` → exit 0, **175/0** сохранено.
  - `grep -cE "^CVE-|^GHSA-|^PYSEC-" .security/pip-audit-allowlist.txt` → **35**.
  - `make check-docstrings MAX_ALLOWED=0` → exit 0.
- **Rollback risk:** **низкий** (`git reset HEAD~1 --soft` восстанавливает working tree).
- **Docstring marker:** не применимо (commit-only).
- **Rationale:** C-11 явно требует developer commit step перед cycle 3 →
  cycle 4 attribution, иначе cycle 3 swarm невозможно отличить от pre-existing.

---

## 2. Wave 1 — P0 security / reliability (6 локальных задач)

> Цель: устранить Tier A blockers из PHASE-2 §4. Каждая задача — atomic
> fix unit, локальная к одному домену, без cross-cutting refactor. Высокий
> parallel signal — 5 из 6 фиксов в **разных файлах**.

### T-02 — Удалить 8 stale CVE из allowlist (DEP-P0-001)

- **Global task ID:** `C3-02`
- **Source finding IDs:** `dependencies:DEPS-P0-001` (PHASE-2 §3.1)
- **Приоритет:** P0 (security gate noise — реальный CVE может пройти незамеченным)
- **Домены:** 11 dependencies
- **Точные пути файлов:** `.security/pip-audit-allowlist.txt` (строки L65, L67,
  L69, L71, L74, L76, L79) + `tools/pip_audit_gate.py` (массив `IGNORED_VULNS`
  строка 18-21, удалить `PYSEC-2026-87`).
- **Минимальный diff:**
  - `.security/pip-audit-allowlist.txt`: удалить 8 строк (PYSEC-2026-161,
    CVE-2026-46645, CVE-2026-45739, GHSA-mv93-w799-cj2w, PYSEC-2026-142,
    PYSEC-2026-141, CVE-2026-45409, PYSEC-2026-87).
  - `tools/pip_audit_gate.py`: удалить `PYSEC-2026-87` из `IGNORED_VULNS`.
  - **Ожидаемое количество** active IDs после правки: `35 - 8 = 27`.
- **Зависимости:** нет
- **Параллельность:** PG-1 (параллельно с T-03, T-04, T-05, T-06, T-07)
- **LOC range:** −8 (только удаление)
- **Критерий "готово":**
  - `.venv/bin/python -m pytest tools/tests/test_pip_audit_gate.py -x` → exit 0
    (если теста нет — `python -c "import ast; ast.parse(open('tools/pip_audit_gate.py').read())"`).
  - `grep -cE "^CVE-|^GHSA-|^PYSEC-" .security/pip-audit-allowlist.txt` → **27**.
  - `make audit-deps` → exit 0 (allowlist после удаления не должен срабатывать
    на удалённые ID — installed versions ≥ fix).
  - `python -c "import tomllib; tomllib.loads(open('pyproject.toml','rb').read())"` → exit 0.
- **Rollback risk:** **низкий** (восстановить 8 строк + 1 запись в `IGNORED_VULNS`).
- **Docstring marker:** `# cycle-3/D-AUDIT-02` в шапке `tools/pip_audit_gate.py`
  рядом с комментарием «8 stale CVE удалены per phase-3/C3-02».
- **Rationale:** C-1..C-15 не затрагивают; PHASE-2 §3.1 Tier A #A23 — блокер
  security gate.

### T-03 — Streamlit upper bound (DEP-P0-002)

- **Global task ID:** `C3-03`
- **Source finding IDs:** `dependencies:DEPS-P0-002` (PHASE-2 §3.1, Tier A #A24)
- **Приоритет:** P0 (95 streamlit imports → runtime fail при 2.x)
- **Домены:** 11 dependencies
- **Точные пути файлов:** `pyproject.toml` строка 137 (`streamlit>=1.58.0`).
- **Минимальный diff:** одна строка → `streamlit>=1.58.0,<2.0.0`.
- **Зависимости:** нет
- **Параллельность:** PG-1 (параллельно с T-02, T-04, T-05, T-06, T-07)
- **LOC range:** +0/−0 (edit 1 строку)
- **Критерий "готово":**
  - `.venv/bin/python -m pytest tests/unit/dependencies -x` (если существует) →
    exit 0. **Если тестов нет:** `python -c "import tomllib; t=tomllib.loads(open('pyproject.toml','rb').read()); assert any('streamlit' in d for d in [t['project']['dependencies']])"` → exit 0.
  - `grep -n "streamlit" pyproject.toml` показывает `,<2.0.0` суффикс.
  - **uv.lock не изменился** (baseline-инвариант: -15 svcs drift не растёт).
- **Rollback risk:** **очень низкий** (1 строка).
- **Docstring marker:** `# cycle-3/D-AUDIT-03` в `pyproject.toml` через inline
  comment после строки.
- **Rationale:** §7 PHASE-2 подтверждает `streamlit` installed, `<2.0.0`
  никаких API-breaks не вызовет (текущая кодовая база совместима с 1.58+).

### T-04 — 4-way CVE enforcement unification (DEP-P0-003)

- **Global task ID:** `C3-04`
- **Source finding IDs:** `dependencies:DEPS-P0-003` (PHASE-2 §3.1, Tier A #A25)
- **Приоритет:** P0 (inconsistent enforcement — GitLab CI fail, GH pass)
- **Домены:** 11 dependencies
- **Точные пути файлов:**
  - `Makefile` (или `make/security.mk` если существует) — primary source.
  - `.github/workflows/security.yml` (строки 1-50, area pip-audit).
  - `.gitlab/ci/.gitlab-ci.yml` (строки 1-50, area pip-audit).
  - `tools/pip_audit_gate.py` строки 18-21 (уже очищены в T-02 от IGNORED_VULNS).
- **Минимальный diff:** все 4 enforcement сайта должны вызывать единый
  `make audit-deps` (или `python tools/pip_audit_gate.py`). Конкретные строки
  — к удалению в workflow/CI; Makefile остаётся canonical.
  - `.github/workflows/security.yml`: `pip-audit -r requirements.txt --strict` →
    `make audit-deps` (или `python tools/pip_audit_gate.py`).
  - `.gitlab/ci/.gitlab-ci.yml`: аналогично.
  - `tools/pip_audit_gate.py`: read `.security/pip-audit-allowlist.txt` (уже
    делает per §1.1 PHASE-2).
- **Зависимости:** T-02 (потому что T-02 чистит allowlist; unification должна
  идти после, иначе в CI поедет stale allowlist)
- **Параллельность:** PG-2 (после T-02, T-03; параллельно с T-05, T-06, T-07)
- **LOC range:** −10/+5 net
- **Критерий "готово":**
  - `.venv/bin/python -m pytest tests/unit/tools -x` → exit 0 (если применимо).
  - `make audit-deps` → exit 0 (canonical).
  - `grep -r "pip-audit" .github/workflows/ .gitlab/ci/ Makefile tools/pip_audit_gate.py` →
    все 4 ссылки указывают на единый entrypoint.
  - `make audit-deps && echo OK` → exit 0.
- **Rollback risk:** **средний** (если CI упадёт после unification — возможен
  drift в allowlist, но T-02 уже подтвердил что 8 stale ID не нужны).
- **Docstring marker:** `# cycle-3/D-AUDIT-04` в `tools/pip_audit_gate.py`
  header comment.
- **Rationale:** C-2 (WorkflowFlags default lie) и C-4 (CDC vs ClickHouse DLQ)
  НЕ относятся; A25 явно — блокер CI consistency.

### T-05 — Hardcoded shutdown timeout (settings:DOMAIN-P0-002)

- **Global task ID:** `C3-05`
- **Source finding IDs:** `settings:DOMAIN-P0-002` (PHASE-2 §3.1, Tier A #A18)
- **Приоритет:** P0 (k8s grace budget 30−15=15s, hardcode 10s съедает 2/3)
- **Домены:** 12 settings
- **Точные пути файлов:**
  - `src/backend/plugins/composition/lifecycle/shutdown.py:199` — параметризовать
    `timeout` через `settings.app.graceful_shutdown_timeout`.
  - `src/backend/core/config/settings/app.py` (или `lifecycle.py`) — добавить поле
    `graceful_shutdown_timeout: int = 15` (Pydantic-settings).
- **Минимальный diff:**
  - `shutdown.py:199`: `task_registry.shutdown_all(timeout=settings.app.graceful_shutdown_timeout)`.
  - `settings/app.py`: добавить `graceful_shutdown_timeout: int = Field(default=15, ge=5, le=60)`.
- **Зависимости:** нет
- **Параллельность:** PG-1 (параллельно с T-02, T-03, T-04, T-06, T-07)
- **LOC range:** +3/−1
- **Критерий "готово":**
  - `.venv/bin/python -m pytest tests/unit/core/config/test_settings_app.py -x`
    (если существует) → exit 0. **Альтернативно:**
    `.venv/bin/python -c "from src.backend.plugins.composition.lifecycle.shutdown import shutdown_all; import inspect; src=inspect.getsource(shutdown_all); assert 'graceful_shutdown_timeout' in src"` → exit 0.
  - `.venv/bin/python -m pytest tests/unit/core/config -k shutdown -x` → exit 0.
  - `make check-docstrings MAX_ALLOWED=0` → exit 0 (новое поле получит docstring).
- **Rollback risk:** **низкий** (revert 2 строки, default сохраняет 10s для обратной совместимости при ошибке).
- **Docstring marker:** `# cycle-3/D-AUDIT-05` в docstring поля `graceful_shutdown_timeout`.
- **Rationale:** C-2 (default vs description) и C-4 (DLQ) не затрагивают; A18
  — единственный production-критичный P0 в settings (после FIX P0-003 Granian
  CLI flag в cycle 3).

### T-06 — Test-infra sink/DLQ conftest (infrastructure:01-P1-NEW-001 → P0)

- **Global task ID:** `C3-06`
- **Source finding IDs:** `infrastructure:01-P1-NEW-001` (PHASE-2 §3.1, Tier B #B1)
- **Приоритет:** **P0** (escalate: ~40 failing tests, маскирует fail-closed
  semantics DLQ — сопоставимо с TM-1..TM-5)
- **Домены:** 01 infrastructure
- **Точные пути файлов:**
  - `tests/unit/infrastructure/sinks/conftest.py:1-28` — добавить autouse fixture.
  - `tests/unit/infrastructure/messaging/dlq/conftest.py` (если существует) —
    аналогично.
- **Минимальный diff:**
  ```python
  # tests/unit/infrastructure/sinks/conftest.py (add at top, после imports)
  # cycle-3/D-AUDIT-06
  @pytest.fixture(autouse=True)
  def _grant_sink_capabilities(request):
      """Grant dlq.write/file.write/ws.send для тестов с @require_capability.
      Production fail-closed semantics сохраняется; тесты получают capabilities,
      чтобы не падать на capability check.
      """
      # pattern: enumerate request.fixturenames → set capabilities
      from src.backend.core.security.capabilities import grant_runtime_capability
      for cap in ("dlq.write", "file.write", "ws.send", "s3.write", "mq.publish"):
          grant_runtime_capability(cap, scope="test", source="conftest")
      yield
  ```
  Точная сигнатура `grant_runtime_capability` верифицируется разработчиком;
  если API отличается — адаптировать под существующий pattern в `conftest.py`
  (см. существующий `dlq.conftest.py` если есть аналог).
- **Зависимости:** нет
- **Параллельность:** PG-1 (параллельно с T-02..T-05, T-07)
- **LOC range:** +12/+20
- **Критерий "готово":**
  - `.venv/bin/python -m pytest tests/unit/infrastructure/sinks -x --tb=short` → exit 0
    (ранее ~40 fails; после fix → 0 fails или ≤2 pre-existing).
  - `.venv/bin/python -m pytest tests/unit/infrastructure/messaging -x` → exit 0.
  - `make audit-deps` → exit 0 (unrelated, baseline check).
  - Production code (`src/backend/infrastructure/sinks/...`) — НЕ затронут,
    проверка: `git diff src/backend/infrastructure/sinks/ | wc -l` → 0.
- **Rollback risk:** **низкий** (autouse fixture легко отключить, удалив декоратор).
- **Docstring marker:** `# cycle-3/D-AUDIT-06` в conftest module docstring.
- **Rationale:** A18 + B1 — без visibility test-infra, maskированные TM-1..TM-5
  остаются скрытыми; B17 cycle-37 pattern (DLQ-writer guard) уже дал
  architectural precedent.

### T-07 — WorkflowFlags defaults fix (workflow:DOMAIN-WF-P0-001)

- **Global task ID:** `C3-07`
- **Source task ID:** `workflow:DOMAIN-WF-P0-001` (PHASE-2 §3.1, Tier A #A14)
- **Приоритет:** P0 (config lie → silent operator surprise → BPMN/gateway
  compiler half-baked code active by default)
- **Домены:** 07 workflow
- **Точные пути файлов:** `src/backend/core/config/features/workflow.py:32-72`.
- **Минимальный diff:** 4 флага (`workflow_legacy_disabled`, `workflow_yaml_round_trip`,
  `workflow_bpmn_import`, `workflow_gateways_enabled`) — изменить default
  `True` → `False` + обновить `Field(description=...)` чтобы соответствовать.
  - **C-2 caveat:** default = False предполагает, что `credit_pipeline_v2`
    (BL-P1-002) тоже потребует аналогичной правки в `plugins.py:41-52` —
    **но это отдельная задача** (T-09 в Wave 2; см. C-2 «нужна верификация
    архитектором»). Cycle 3 фиксирует только `workflow.py` (явный P0 с
    production impact per A14); `plugins.py` — отдельный P1.
- **Зависимости:** нет
- **Параллельность:** PG-1 (параллельно с T-02..T-06)
- **LOC range:** +4/−4 (4 строки edit + 4 строки description update)
- **Критерий "готово":**
  - `.venv/bin/python -m pytest tests/unit/core/config/features/test_workflow_flags.py -x`
    (если существует; иначе создать — см. ниже). Exit 0.
  - **Если тестов нет:** создать `tests/unit/core/config/features/test_workflow_flags.py`
    ~20 LOC с 4 assertion'ами `assert WorkflowFlags().workflow_legacy_disabled is False` (etc.).
    `.venv/bin/python -m pytest tests/unit/core/config/features/test_workflow_flags.py -v` → 4 passed.
  - `grep -nE "workflow_legacy_disabled|workflow_yaml_round_trip|workflow_bpmn_import|workflow_gateways_enabled" src/backend/core/config/features/workflow.py` →
    все 4 имеют `= False`.
  - `make check-docstrings MAX_ALLOWED=0` → exit 0.
- **Rollback risk:** **низкий** (4 строки revert; default True восстановим
  немедленно).
- **Docstring marker:** `# cycle-3/D-AUDIT-07` в class docstring
  `WorkflowFlags` (одна строка комментария).
- **Rationale:** A14 прямо указано как P0 с production impact; C-2 разделяет
  workflow vs plugins (разные default-конвенции), cycle 3 фиксирует только
  workflow-часть.

---

## 3. Wave 2 — P1 layer track (2 задачи)

> Цель: устранить P1-блокеры одного слоя (test-infra → test-masking cascade
> и слой layer-трека), чтобы разблокировать «green-light» для test-masking
> фиксов из PHASE-2 §1.4 (TM-1..TM-5).

### T-08 — TenantFacade kwargs fix (services:DOMAIN-P0-001 → P1-wave-2)

- **Global task ID:** `C3-08`
- **Source finding IDs:** `services:DOMAIN-P0-001` (PHASE-2 §3.1, Tier A #A1)
- **Приоритет:** P1 (escalate из-за блокировки TM-2; см. C-9 PHASE-2)
- **Домены:** 03 services (cross: entrypoints test-masking)
- **Точные пути файлов:**
  - `src/backend/services/tenancy/facade.py:116` — `with_tenant()` исправить
    `tenant_id=` → позиционный `id` или обновить `CapabilityTenant.__init__` signature.
  - `src/backend/core/security/capabilities/tenant.py` (или аналог с
    `CapabilityTenant.__init__`) — выровнять signature.
- **Минимальный diff:** ~3 строки. Привести в соответствие kwargs call и
  `__init__` signature. Минимальный вариант:
  - facade: `CapabilityTenant(id=tenant_id, principal=principal, scope_glob=scope_glob)`
    (заменить `tenant_id=tenant_id` → `id=tenant_id`).
  - **Альтернатива:** добавить `tenant_id: str | None = None` параметр в
    `__init__` с `self.id = tenant_id or self.id` fallback (если facade pattern
    предполагает `tenant_id=`).
  - Выбор — на разработчике после верификации `CapabilityTenant.__init__`
    signature. Cycle 3 фиксирует только intent.
- **Зависимости:** нет
- **Параллельность:** PG-3 (после T-07; параллельно с T-09)
- **LOC range:** +2/−2
- **Критерий "готово":**
  - `.venv/bin/python -m pytest tests/unit/services/test_facades.py::TestTenantFacade::test_with_tenant_restores_previous -v` → 1 passed
    (cycle 2 PHASE-2 §1.4: «deselected/exit 1, masks TypeError»).
  - `.venv/bin/python -m pytest tests/unit/services/tenancy -x` → exit 0.
  - `python -c "from src.backend.services.tenancy.facade import TenantFacade; t = TenantFacade(); t.with_tenant('x', lambda: None)"` → exit 0 (no TypeError).
- **Rollback risk:** **низкий** (3 строки; сигнатура изменяется только в одном
  направлении — id/tenant_id).
- **Docstring marker:** `# cycle-3/D-AUDIT-08` в docstring `with_tenant`.
- **Rationale:** A1 + TM-2 (PHASE-2 §1.4) — фикс открывает test-masking
  cascade и разблокирует `test_with_tenant_restores_previous`.

### T-09 — Credit pipeline flag default consistency (BL-P1-002)

- **Global task ID:** `C3-09`
- **Source finding IDs:** `business-logic:BL-P1-002` (PHASE-2 §3.2, Tier B #B18)
- **Приоритет:** P1 (test suite блокируется `assert True is False`)
- **Домены:** 10 business-logic
- **Точные пути файлов:** `src/backend/core/config/features/plugins.py:41-52`.
- **Минимальный diff:** `credit_pipeline_v2: bool = True` → `False` + update
  `Field(description=...)` чтобы соответствовать.
  - **C-2 caveat:** T-07 (workflow flags) и T-09 (plugins flag) — оба
    follow-up от C-2 «нужна верификация default-convention». Cycle 3
    фиксирует оба одинаково (False); cycle 4 может пересмотреть, если
    архитектор решит иначе.
- **Зависимости:** нет
- **Параллельность:** PG-3 (параллельно с T-08)
- **LOC range:** +1/−1
- **Критерий "готово":**
  - `.venv/bin/python -m pytest tests/unit/extensions/credit_pipeline/test_credit_pipeline_v2_flag.py -v` → 1 passed
    (если тест существует per BL-P1-002).
  - **Если теста нет:** создать ~15 LOC test
    `tests/unit/extensions/credit_pipeline/test_credit_pipeline_v2_flag.py` с
    `assert PluginFlags().credit_pipeline_v2 is False`. `.venv/bin/python -m pytest tests/unit/extensions/credit_pipeline/test_credit_pipeline_v2_flag.py -v` → 1 passed.
  - `grep -n "credit_pipeline_v2" src/backend/core/config/features/plugins.py` →
    `= False`.
  - `make check-docstrings MAX_ALLOWED=0` → exit 0.
- **Rollback risk:** **низкий** (1 строка).
- **Docstring marker:** `# cycle-3/D-AUDIT-09` в docstring поля `credit_pipeline_v2`.
- **Rationale:** B18 (test suite блокируется); C-2 — общая default-convention
  fix с T-07; **только** после T-07 для согласованности (sequence внутри PG-3).

---

## 4. Wave 3 — P3 library replacement (1 задача)

> Цель: выполнить **одну** P3-замену с явным positive evidence (installed +
> recommended per PHASE-2 §7). Остальные P3 — DEFER (negative findings;
> см. PHASE-2 §7 summary: 3 APPLIED, 4 RECOMMENDED, 7 NO-OP, 2 verify, 1 partial).

### T-10 — defusedxml drop-in для `_xml_to_dict_stdlib` (DSL-P0-003 + DSL-P3-001)

- **Global task ID:** `C3-10`
- **Source finding IDs:** `dsl:DSL-P0-003` (PHASE-2 §3.1, Tier B #B4) +
  `dsl:DSL-P3-001` (consolidation)
- **Приоритет:** P3 (latent vuln в fallback; dead path in prod, но cycle 3
  доказательства — active vuln подтверждён)
- **Домены:** 06 dsl
- **Точные пути файлов:**
  - `src/backend/dsl/engine/processors/format_convert/data_formats.py:61-66`
    (удалить функцию `_xml_to_dict_stdlib` или заменить на `defusedxml.ElementTree`).
  - `src/backend/dsl/engine/processors/format_convert/encodings.py:63-66`
    (дубликат — удалить).
  - `src/backend/dsl/engine/processors/format_convert/specialized.py:61-64`
    (дубликат — удалить).
- **Минимальный diff:** ~−30 LOC net (3-way triplication → 0; defusedxml 0.7.1
  installed, `defusedxml.ElementTree.fromstring` уже используется per §7).
  - **Стратегия:** заменить `xml.etree.ElementTree.fromstring` →
    `defusedxml.ElementTree.fromstring` во всех 3 файлах; удалить функцию
    `_xml_to_dict_stdlib` (дубликация с `xmltodict.parse`, PHASE-2 §7).
  - **Альтернатива (минимальная):** удалить функцию полностью; callers
    используют `xmltodict.parse` (0.15.1 installed).
- **Зависимости:** нет
- **Параллельность:** PG-4 (после T-08, T-09; independent)
- **LOC range:** −20/−40 net
- **Критерий "готово":**
  - `.venv/bin/python -m pytest tests/unit/dsl/format_convert -v` → exit 0.
  - `.venv/bin/python -m pytest tests/unit/dsl/eip/marshal -v` → exit 0.
  - `grep -rn "_xml_to_dict_stdlib" src/` → 0 hits (или только в dead `__pycache__`).
  - `grep -rn "xml.etree.ElementTree" src/backend/dsl/engine/processors/format_convert/`
    → 0 hits (заменено на defusedxml).
- **Rollback risk:** **низкий** (`git revert` восстанавливает 3 файла).
- **Docstring marker:** `# cycle-3/D-AUDIT-10` в docstring модуля
  `format_convert/__init__.py` (одна строка: «XML парсинг переведён на defusedxml per cycle-3/C3-10»).
- **Rationale:** PHASE-2 §7 explicit RECOMMENDED; единственный P3 с positive
  replacement (defusedxml installed, xmltodict installed, triplication cleanup).

---

## 5. Wave 4 — P4 organic feature (1 задача)

> Цель: один organic feature с явным use case и Ponytail-friendly effort
> (≤120 LOC, per PHASE-2 §8 «Sprint 37+»).

### T-11 — text-RAG E2E test (rag:RAG-P4-001, structural debt)

- **Global task ID:** `C3-11`
- **Source finding IDs:** `rag:RAG-P4-001` (PHASE-2 §3.5, T-4.1 cycle-1 RESIDUAL,
  T-W4-01 cycle-2 RESIDUAL)
- **Приоритет:** P4 (organic feature / structural debt; 2 раза deferred)
- **Домены:** 09 rag
- **Точные пути файлов:** `tests/e2e/test_text_rag_e2e.py` (создать).
- **Минимальный diff:** ~100 LOC. Структура:
  - 1 ingest doc (`text_ingest` fixture с `tenant_id="e2e-text"`).
  - 1 query (`text_query` с тем же `tenant_id`).
  - 1 assertion (top-k ≥ 1 hit, attribution present).
  - marker `# cycle-3/D-AUDIT-11` в module docstring.
- **Зависимости:** нет (RAG ingest/query API уже exposed per PHASE-2 §2 strengths #9)
- **Параллельность:** PG-4 (параллельно с T-10; independent)
- **LOC range:** +80/+120
- **Критерий "готово":**
  - `.venv/bin/python -m pytest tests/e2e/test_text_rag_e2e.py -v` → 1 passed.
  - **Caveat:** если ingest требует embedding-сервис (live) — test может
    skip через `@pytest.mark.skipif(not has_embeddings, reason="...")`. Cycle 3
    принимает skip как PASS, если pytest exit 0.
  - `make check-docstrings MAX_ALLOWED=0` → exit 0 (new test file
    docstring'd).
  - `.venv/bin/python -m pytest tests/e2e -v --co -q | head -20` → exit 0
    (collection clean).
- **Rollback risk:** **очень низкий** (удалить файл).
- **Docstring marker:** `# cycle-3/D-AUDIT-11` в module docstring `test_text_rag_e2e.py`.
- **Rationale:** PHASE-2 §8 «CRITICAL: structural debt»; 2 раза deferred
  (cycle 1 T-4.1, cycle 2 T-W4-01); единственный P4 с structural impact;
  Ponytail-friendly (≤120 LOC).

---

## 6. Wave N — Deferred в cycle 4+ (1 задача)

> Цель: явно перечислить, что НЕ делается в cycle 3 и почему. Cycle 4+
> получит новый plan с обновлёнными приоритетами.

### T-12 — Temporal Worker lifecycle (workflow:DOMAIN-WF-P0-003 + P0-004) → DEFER

- **Global task ID:** `C3-12` (DEFERRED)
- **Source finding IDs:** `workflow:DOMAIN-WF-P0-003` + `DOMAIN-WF-P0-004`
  (PHASE-2 §3.1, Tier A #A13)
- **Приоритет:** DEFER (HIGH risk, HIGH effort, требует ADR-045 verification)
- **Домены:** 07 workflow + 11 dependencies
- **Точные пути файлов:** `src/backend/infrastructure/workflow/temporal_client.py:227-321`
  + `src/backend/dsl/workflow/compiler/activity_bridge.py:288-305` +
  `src/backend/infrastructure/workflow/worker_runtime.py` (создать).
- **Причина DEFER:**
  1. C-8 явно требует верификации архитектором: «Temporal = production
     target или pg_runner is production?». Cycle 3 НЕ может решить ADR-level
     вопрос.
  2. Если pg_runner is production → Temporal = YAGNI (P3 remove, как cycle 2
     P0-005 для DOMAIN-WF-P3-001).
  3. Если Temporal = production → требуется ~5d effort (PHASE-2 §6
     «WS-1.5»), отдельный sprint (38+).
  4. Cycle 3 фокус — P0-fixable без ADR-блокировки (см. T-02..T-09).
- **Параллельность:** N/A (deferred)
- **LOC range:** N/A
- **Критерий "готово":** N/A в cycle 3; cycle 4 plan сформулирует
  на основе ADR-045 decision.
- **Rollback risk:** N/A
- **Docstring marker:** N/A в cycle 3.
- **Rationale:** A13 explicit, но C-8 блокирует до архитектурного решения;
  PR-N на cycle 4.

### Дополнительные DEFER-кандидаты (для cycle 4+ roadmap, не C3-12)

- `settings:DOMAIN-P0-001` (compose resource limits) — downgrade до P3 per
  C-5 (dev/staging parity only; k8s+helm has limits).
- `settings:DOMAIN-P0-004` (Gran CLI surface dup) — duplicate, не
  production-blocker.
- `settings:DOMAIN-P1-001..002` (Granian consolidation + config_audit fix) —
  P1 cleanup, dev experience.
- `infrastructure:01-P2-NEW-001` (compensating_driver dead placeholder) —
  P2 dead code.
- `services:DOMAIN-P1-001..004` (data_quality consolidation, shim callers,
  cron dashboard) — P1, но не блокируют ≥80 порог (PHASE-2 §9).
- `api:API-P0-001` (HITL authz), `api:API-P0-002` (admin_cron RCE) — P0,
  но требуют deeper review (PHASE-2 §3.1; cycle 3 фокус на CVE/timeout/conftest
  для сохранения minimal-diff).
- `entrypoints:DOMAIN-P0-001` (SSE principal), `entrypoints:DOMAIN-P0-002`
  (MQ ACK vs DLQ), `agents:DOMAIN-P0-001..003` (AI service factory,
  AGENT_TOOL_POLICY_FAIL_OPEN, gateway split), `rag:RAG-P0-001..003` (PII
  SystemExit, Prewarmer, factory), `services:DOMAIN-P0-002..005` (admin
  audit/DLQ, PII fail-open, AuthZ fail-open), `security:DOMAIN-P0-001..003`
  (validate_sql, AuthValidateProcessor, audit data-loss), `dsl:DSL-P0-001..002`
  (scan_file, marshal XXE) — все Tier A, но cycle 3 minimal-diff фокус
  выбрал 6 P0 с минимальным cross-cutting impact (T-02..T-07). Остальные
  Tier A — cycle 4+ candidates (PHASE-2 §6 рекомендует Sprint 37+).
- `business-logic:BL-P0-001` (dead saga imports) — P0, но требует решения
  «удалить vs создать extension stubs» (PHASE-2 §3.1 + C-13). Cycle 4
  architectural decision.
- `workflow:DOMAIN-WF-P0-002` (4 processors без `@processor`) — P0, atomic
  fix (~10 LOC), но в cycle 3 фокус T-07 (WorkflowFlags) — один workflow
  P0 для minimal-diff; cycle 4 добавит оставшиеся.
- `workflow:DOMAIN-WF-P0-005` (cancel vs invoke sync semantics) — P0,
  cross-file, ~15 LOC; cycle 4.
- Все test-masking fixes кроме T-08 (TM-1 MQ, TM-3 audit coroutine, TM-4
  TemporalWorkerPool, TM-5 LangGraph) — cycle 4+ (PHASE-2 §6 WS-3 требует
  batch после T-06 visibility).
- Все `business-logic:BL-P1-001` (OSINT fail-OPEN) и `BL-P2-*` — cycle 4+.
- Все `settings:DOMAIN-P1-002` (config_audit path fix) — 1-line fix,
  но cycle 3 не делает settings P1 (PHASE-2 §9 cap satisfied для
  settings-environment при 0 NEW P0/P1).

---

## 7. Dependency graph + parallel groups

### 7.1 Topological order (DAG)

```
T-01 (Wave 0, serial, blocker)
   │
   ▼
T-02 (PG-1) ─┐
T-03 (PG-1) ─┤
T-04 (PG-2, после T-02)
T-05 (PG-1) ─┤
T-06 (PG-1) ─┤
T-07 (PG-1) ─┘
   │
   ▼
T-08 (PG-3, после T-07)
T-09 (PG-3, после T-07)
   │
   ▼
T-10 (PG-4, после T-08, T-09)
T-11 (PG-4, parallel с T-10)
   │
   ▼
T-12 (DEFER, cycle 4+)
```

### 7.2 Параллельные группы (parallel groups)

| PG | Задачи | Параллельность | Notes |
|---|---|---|---|
| **PG-1** | T-02, T-03, T-05, T-06, T-07 | 5 одновременно | Все в разных файлах; ни одна не меняет source composition root. T-04 НЕ здесь — он ждёт T-02. |
| **PG-2** | T-04 (после T-02) | 1 задача | Unification 4-way CVE enforcement — требует чистого allowlist от T-02. |
| **PG-3** | T-08, T-09 (parallel, оба после T-07) | 2 одновременно | Разные домены (services vs business-logic); оба следуют C-2 default-convention fix. |
| **PG-4** | T-10, T-11 (parallel, оба после PG-3) | 2 одновременно | Разные домены (dsl vs rag); Ponytail-friendly пара. |

### 7.3 Top dependencies (chain, longest path)

1. **T-01 → T-02 → T-04** (developer commit → allowlist cleanup → CI unification)
2. **T-01 → T-07 → T-08 → T-10** (developer commit → workflow flags → tenant
   facade kwargs → XML consolidation)
3. **T-01 → T-06 → TM-cascade cycle 4+** (developer commit → test-infra
   conftest → разблокирует visibility для cycle 4 test-masking batch)
4. **T-01 → T-12 (DEFER)** (developer commit → ADR-045 → Temporal lifecycle)

Longest chain по LOC-effort: T-01 (0) → T-07 (4) → T-08 (3) → T-10 (−30 net)
= ~−23 LOC, ~2-3h суммарно.

### 7.4 Одновременно-выполнимые max параллельно: **5** (PG-1)

С учётом PG-2..PG-4: пиковый параллелизм — 5 веток (T-02, T-03, T-05, T-06, T-07).
После завершения PG-1 → 2 ветки (PG-2 = T-04, PG-3 = T-08 + T-09). Затем PG-4
= 2 ветки (T-10 + T-11).

---

## 8. Definition of Done (DoD) — Cycle 3

Все 11 инвариантов должны выполняться **после** каждой завершённой задачи
(а не только в финале):

| # | Инвариант | Команда проверки | Ожидаемое значение |
|---|---|---|---|
| 1 | Layer checker | `python tools/check_layers.py --root src` | exit 0, **175 legacy / 0 new** (2274 файлов) |
| 2 | Security allowlist | `grep -cE "^CVE-|^GHSA-|^PYSEC-" .security/pip-audit-allowlist.txt` | **27** (после T-02; до T-02 = 35) |
| 3 | Docstring gate | `make check-docstrings MAX_ALLOWED=0` | exit 0, 0 missing |
| 4 | Runtime | `.venv/bin/python -m pytest <changed-paths> -x` | exit 0 |
| 5 | uv.lock churn | `git diff uv.lock | wc -l` (от HEAD) | 0 lines (pre-existing -15 svcs drift не растёт) |
| 6 | Pre-existing drift | `git status --short` показывает pre-existing drift | `M uv.lock`, `?? pip-audit.json`, `?? .blue_green.state` (после T-01) |
| 7 | Pre-existing residual | `grep -n "except Exception: pass" src/backend/services/ai/gateway_adapter.py` | совпадает с baseline (НЕ затронут) |
| 8 | Uncommitted cycle-1/2 | `git log --oneline -1` после T-01 | новый commit «chore: commit cycle-1/2 preflight uncommitted» |
| 9 | Test-masking fixes | TM-2 fix verified per T-08 (cycle 2 PHASE-2 §1.4 + cycle 3 PHASE-2 §1.4) | `test_with_tenant_restores_previous` passes |
| 10 | Docstring markers | `grep -rn "cycle-3/D-AUDIT" src/ tests/` | все 11 задач (C3-02..C3-11) имеют маркер |
| 11 | Composition root | `git diff src/backend/plugins/composition/ | wc -l` | 0 lines (composition root НЕ затронут в cycle 3) |

**Cycle 3 PASS** = все 11 инвариантов ✓ после выполнения всех 11 задач
(задачи C3-01..C3-11; C3-12 DEFER).

---

## 9. Причины DEFER в cycle 4+ (явный список)

| # | Категория | Findings | Причина |
|---|---|---|---|
| 1 | ADR-045 verification | workflow:DOMAIN-WF-P0-003 + P0-004 (T-12) | C-8 блокирует (Temporal vs pg_runner); cycle 4 после архитектурного решения |
| 2 | Cross-cutting fail-open cascade | services:DOMAIN-P0-002..005, security:DOMAIN-P0-001..003, agents:DOMAIN-P0-001..003, rag:RAG-P0-001..003, entrypoints:DOMAIN-P0-001..002, api:API-P0-001..002 | Cycle 3 minimal-diff фокус выбрал 6 P0 (T-02..T-07) с минимальным cross-cutting; остальные Tier A — cycle 4+ Sprint 37 candidates (PHASE-2 §6) |
| 3 | Test-masking TM-1, TM-3, TM-4, TM-5 | entrypoints DLQ, security audit, workflow Temporal, agents LangGraph | T-06 (conftest) разблокирует visibility; TM batch — cycle 4 после PG-1 visibility |
| 4 | Workflow DSL registration + sync semantics | workflow:DOMAIN-WF-P0-002 (4 processors), P0-005 (cancel/invoke) | Atomic, но в cycle 3 — один workflow P0 (T-07) для minimal-diff; cycle 4 — остальные |
| 5 | Extensions P1/P2 cleanup | business-logic:BL-P1-001 (OSINT), BL-P2-* | Cycle 3 фокус — core/security; extensions — cycle 4 |
| 6 | Library replacement candidates (negative) | 7 NO-OP + 2 verify + 1 partial (PHASE-2 §7) | DEFER по дизайну (Ponytail YAGNI) |
| 7 | Organic features Sprint 38+ | workflow:DOMAIN-WF-P4-001..003, api:API-P4-001..002, rag:RAG-P4-002, settings:DOMAIN-P4-001 | PHASE-2 §8 explicit Sprint 38+ |
| 8 | Pre-existing test failures | WS-10 (5 fails gateway_pipeline, 9 outbox, 4 tenant_filter, 2 inbox, 4 cdc_status_docs, 1 vault, 1 extensions_layer, 1 smart_session_manager, 5 unmasked) | BASELINE — не атрибутируется cycle 3; developer commit step (T-01) фиксирует attribution, cycle 4 — fix |
| 9 | Settings RESIDUAL P0/P1 | settings:DOMAIN-P0-001 (compose, downgrade до P3 per C-5), P0-004 (Gran dup), P1-001 (Granian consolidation), P1-002 (config_audit path) | Cycle 3 cap satisfied для settings-environment (0 NEW P0/P1 per PHASE-2 §9) |
| 10 | Dead code / stubs P2 | 1 infra + 3 services + 7 entrypoints + 3 api + 2 dsl + 6 workflow + 2 agents + 2 rag + 7 business-logic + 2 deps + 4 settings = ~40 P2 | DEFER (PHASE-2 §3.3; cleanup pass в cycle 4+) |

**Cycle 4 backlog size:** ~140 P0/P1 findings (без composition root critical
path) + ~40 P2 + ~13 P4 — фокус: Tier A (data-loss / fail-open / race) + TM
batch + ADR-045 decision.

---

## 10. Rollback risk summary

| Task | Risk | Reversibility | Notes |
|---|---|---|---|
| T-01 | **очень низкий** | `git reset HEAD~1 --soft` | Developer commit, не правит source |
| T-02 | **низкий** | Восстановить 8 строк + 1 IGNORED_VULNS entry | `git checkout` |
| T-03 | **очень низкий** | 1 строка в `pyproject.toml` | `git checkout` |
| T-04 | **средний** | CI может упасть если union неполон; manual review | Требует верификации 4 sites |
| T-05 | **низкий** | Revert 3 строки, default 10s сохраняется | `git checkout` |
| T-06 | **низкий** | Autouse fixture отключается удалением декоратора | `git checkout` |
| T-07 | **низкий** | Revert 4 строки (default True восстанавливается) | `git checkout` |
| T-08 | **низкий** | Revert 3 строки, kwargs pattern восстанавливается | `git checkout` |
| T-09 | **низкий** | Revert 1 строку | `git checkout` |
| T-10 | **низкий** | `git revert` восстанавливает 3 файла | `git checkout` |
| T-11 | **очень низкий** | Удалить файл | `git rm` |
| T-12 | N/A (DEFER) | N/A | N/A |

**Совокупный worst-case rollback:** ~50 LOC revert + 1 commit revert для
T-01. Все фиксы локальные (1-4 файла каждый); ни один не затрагивает
composition root, `infrastructure/storage/s3.py`, или `tools/blue_green.sh`.

---

## 11. Подпись

- **Никакие файлы source/configs/lockfiles/allowlists не модифицировались.**
  Единственный артефакт — этот `PHASE-3-PLAN.md`.
- **Source-код, `CLAUDE.md`, `PLAN.md`, `KNOWN_ISSUES.md`, cycle-1/cycle-2
  markdown НЕ читались** (только `BASELINE.md` + `PHASE-2-SUMMARY.md`).
- **Конкретные тестовые пути и сигнатуры классов** в DoD — **гипотезы на
  основе PHASE-2 §1.4 / §3 / §6 / §9**; финальная верификация —
  developer на этапе реализации.
- **15 contradictions C-1..C-15** учтены (особенно C-2 default-convention,
  C-8 Temporal ADR, C-9 test-masking cascade, C-11 attribution).
- **5 test-masking issues TM-1..TM-5** подтверждены; T-08 разблокирует TM-2;
  T-06 создаёт visibility для cycle 4 TM batch.
- **Все 11 baseline-инвариантов** в DoD явно прописаны и проверяемы.
- **Rollback plan** — каждая задача reversible в пределах 1-50 LOC.

---

## 12. Возврат родителю

- **Status:** план готов, baseline-инварианты сохранены, 12 задач (11 active
  + 1 DEFER), 4 параллельных группы, top dependencies: T-01 → T-02 → T-04 и
  T-01 → T-07 → T-08 → T-10.
- **Plan path:** `docs/audit/swarm-2026-08-06/cycle-3/PHASE-3-PLAN.md`
- **Количество задач:** 12 (C3-01..C3-12; C3-12 DEFER)
- **Параллельные группы:** 4 (PG-1=5 веток, PG-2=1 ветка, PG-3=2 ветки,
  PG-4=2 ветки); max simultaneous = 5.
- **Top dependencies (chain):**
  1. T-01 (developer commit) — universal blocker.
  2. T-02 (allowlist cleanup) → T-04 (CVE enforcement unification).
  3. T-07 (WorkflowFlags) → T-08 (TenantFacade) → T-10 (XML consolidation).
  4. T-06 (test-infra conftest) → cycle 4 TM batch (DEFER).
- **DoD cycle 3:** 11 инвариантов (см. §8).
- **Cycle 4 backlog:** ~140 P0/P1 + ~40 P2 + ~13 P4 (см. §9).
