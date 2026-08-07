# Cycle 1 — Phase 3 — Архитектурный план реализации

> **Дата:** 2026-08-06
> **HEAD:** `7f3d94a3`
> **Cycle:** 1 (post-Sprint 184)
> **Вердикт Phase 2:** стоп-критерий НЕ выполнен (3/12 доменов ≥80%) — Cycle 1 фокусируется
> на критических P0 фиксах для достижения production sign-off, остальное переносится в Cycle 2.

---

## 1. Стратегия Cycle 1

**Cycle 1 закрывает 13 P0 + 4 P1 (топ-критичные)** — самые блокирующие находки, без которых
production sign-off невозможен:

| Категория | Count | LOC delta |
|---|---|---|
| P0 fixes (security/data-loss) | 13 | +180 / −350 |
| P1 fixes (architecture) | 4 | +50 / −20 |
| Dead code cleanup | 4 | −600 |
| **Итого Cycle 1** | **21 задача** | **+230 / −970** |

**Cycle 2 (планируется отдельно):**
- Оставшиеся 16 P0 (из 29) — после Cycle 1
- Оставшиеся ~46 P1 — top-down по доменам
- P2 dead code (~60 находок) — cleanup PR
- P3 library replacements (~25 находок) — после approval

---

## 2. Task DAG (21 задача, 7 параллельных групп)

### Группа A: A11 fail-open security (5 задач, sequential)

> **Критично:** без закрытия A11 fail-open gate → новые CVE от доработок НЕ блокируются.

#### Task A-1: `tools/pip_audit_gate.py` exit 1 на empty JSON
- **Files:** `tools/pip_audit_gate.py:26-32`
- **Diff:** +20 LOC (добавить `if not data.get("dependencies"): raise GateError`)
- **Done criteria:**
  - `tools/pip_audit_gate.py` → exit 1 на пустой JSON
  - regression test: `tests/unit/tools/test_pip_audit_gate.py::test_empty_json_exits_nonzero`
  - `make check-supply-chain` зелёный

#### Task A-2: `make/security.mk:audit-deps` — добавить `--output pip-audit.json`
- **Files:** `make/security.mk:45-57`
- **Diff:** +2 LOC (добавить `--output pip-audit.json`)
- **Done criteria:**
  - `make audit-deps` создаёт `pip-audit.json` с non-empty content
  - Single source of truth для CI и developer workflow

#### Task A-3: `tests/unit/tools/test_supply_chain_scaffold.py:22` — фикс пути
- **Files:** `tests/unit/tools/test_supply_chain_scaffold.py:22,75`
- **Diff:** −1/+1 LOC (`Makefile.security` → `make/security.mk`)
- **Done criteria:**
  - `uv run pytest tests/unit/tools/test_supply_chain_scaffold.py -v` → 4 passed
  - regression test зелёный

#### Task A-4: SBOM paths unify — single canonical path
- **Files:** `make/security.mk:42`, `tools/checks/generate_sbom.py:99`, `tools/checks/check_supply_chain.py:170`
- **Diff:** ±15 LOC (привести к единому пути `dist/sbom/sbom.cdx.json`)
- **Done criteria:**
  - Все 3 entry point используют `dist/sbom/sbom.cdx.json`
  - `dist/sbom.cdx.json` (legacy) → symlink или удалён
  - regression test на canonical path

#### Task A-5: `dist/sbom.cdx.json` regen через `.venv/bin/python`
- **Files:** `dist/sbom.cdx.json` (артефакт), `.gitignore` или git rm
- **Diff:** регенерация артефакта (вне git)
- **Done criteria:**
  - `dist/sbom.cdx.json` содержит cryptography>=49.0.0 (вместо 41.0.7)
  - `make sbom` создаёт consistent SBOM через `.venv/bin/python`
  - Документация в `tools/cycle-1-preflight.sh` обновлена

---

### Группа B: A8 Temporal Worker runtime (3 задачи, sequential)

> **Критично:** Temporal Worker lifecycle мёртв — production использует только pg-runner.

#### Task B-1: 4 processors через `@processor()` decorator
- **Files:**
  - `src/backend/dsl/engine/processors/workflow/workflow_subprocess.py:24-56`
  - `src/backend/dsl/engine/processors/workflow/workflow_convert.py:23`
  - `src/backend/dsl/engine/processors/workflow/continue_as_new.py:29`
  - `src/backend/dsl/engine/processors/workflow/best_practices/claim_check.py:43`
  - `src/backend/dsl/engine/processors/workflow/best_practices/continue_as_new.py:29`
- **Diff:** +24 LOC (4 × @processor() decorator)
- **Done criteria:**
  - 4 processor'а зарегистрированы через `@processor()`
  - capability-check срабатывает (test: `tests/unit/dsl/test_processor_capabilities.py`)
  - regression test на каждый processor

#### Task B-2: WorkflowFlags `default=True` → `default=False` для 4 флагов
- **Files:** `src/backend/core/config/features/workflow.py:32-72`
- **Diff:** ~0 LOC (изменить default + docstring)
- **Done criteria:**
  - 4 флага (`legacy_disabled`, `yaml_round_trip`, `bpmn_import`, `gateways_enabled`) = `default=False`
  - docstring обновлён
  - test: `tests/unit/core/config/test_workflow_flags.py`

#### Task B-3: Удалить `_bootstrap_default_declarations` (dead code)
- **Files:** `src/backend/plugins/composition/workflow_setup.py:59-89`
- **Diff:** −30 LOC
- **Done criteria:**
  - Функция удалена
  - opt-in flag `bootstrap_default_declarations` удалён
  - regression test на startup без crash

---

### Группа C: A7 DSL processors cleanup (3 задачи, sequential)

#### Task C-1: `security.py:52` deprecated import → fix
- **Files:** `src/backend/dsl/engine/processors/security.py:52`
- **Diff:** +15 LOC (заменить импорт через Pydantic fail-closed pattern)
- **Done criteria:**
  - `AuthValidateProcessor` использует актуальный Pydantic-based verifier
  - fail-closed при отсутствии verifier
  - regression test на каждый scenario

#### Task C-2: `external.py` MCPToolProcessor shadow → rename или удалить
- **Files:** `src/backend/dsl/engine/processors/external.py`
- **Diff:** −30 LOC (если удалить) или ±15 LOC (rename)
- **Done criteria:**
  - Single canonical MCPToolProcessor остаётся (`agent_dsl/*`)
  - dубль из `external.py` удалён или переименован
  - test покрытие single canonical

#### Task C-3: Удалить dead `eip/reliability.py` (442 LOC)
- **Files:** `src/backend/dsl/engine/processors/eip/reliability.py`
- **Diff:** −442 LOC
- **Done criteria:**
  - Файл удалён
  - `eip/reliability/` package directory остаётся canonical
  - Никакие импорты из удалённого файла не сломаны (grep verify)

---

### Группа D: A2 Security WAF + middleware (3 задачи, sequential)

#### Task D-1: `sms_sink.py` WAF coverage fix
- **Files:** `src/backend/infrastructure/sinks/sms_sink.py:109,158`
- **Diff:** +20 LOC (заменить прямой `httpx.AsyncClient` на `core.net.waf_facade`)
- **Done criteria:**
  - `python tools/check_waf_coverage.py` → exit 0
  - regression test на WAF routing

#### Task D-2: `extensions/osint_agent/functions/osint_workflow.py:234` — WAF fix
- **Files:** `extensions/osint_agent/functions/osint_workflow.py:234`
- **Diff:** +20 LOC
- **Done criteria:**
  - WAF покрытие для extensions/* добавлено (расширить scan scope)
  - regression test

#### Task D-3: OtelMiddleware concurrency fix
- **Files:** `src/backend/entrypoints/middlewares/otel_middleware.py:125-126`
- **Diff:** +8 LOC (заменить instance state на contextvar)
- **Done criteria:**
  - Concurrency bug устранён (closure-based state)
  - regression test на concurrent requests

---

### Группа E: A1 + A3 + A5 + A10 + A12 P0 fixes (7 задач, параллельно по файлам)

#### Task E-1: A1 — `AuditEventLog._flush_to_clickhouse` silent loss → DLQ
- **Files:** `src/backend/infrastructure/audit/event_log.py:112-113`
- **Diff:** +60 LOC (скопировать паттерн из ClickHouseAuditService)
- **Done criteria:**
  - `AuditEventLog` использует DLQWriter Protocol при сбое ClickHouse
  - regression test: `tests/unit/infrastructure/audit/test_event_log_dlq.py`
  - Никаких silent losses

#### Task E-2: A3 — admin API fail-CLOSED
- **Files:** `src/backend/services/admin/api.py:97-102`
- **Diff:** +15 LOC (default `fail_closed=True` в AuthZ недоступности)
- **Done criteria:**
  - При AuthZ unavailable → 503 + audit-event (НЕ 200 OK)
  - regression test: `tests/unit/services/admin/test_authz_fail_closed.py`

#### Task E-3: A3 — ClickHouseAuditService silent_loss metric
- **Files:** `src/backend/services/audit/clickhouse_audit_service/service.py:220-223`
- **Diff:** +10 LOC (добавить `_logger.critical` + Prometheus counter)
- **Done criteria:**
  - `_send_to_dlq` логирует critical + emit metric
  - regression test на metric increment

#### Task E-4: A5 — schema-registry TypedAdapter wrapper
- **Files:** `src/backend/services/schema_registry/registry.py:251-270`
- **Diff:** +30 LOC (replace `dict[str, Any]` fallback с TypeAdapter)
- **Done criteria:**
  - Generic typed wrapper на публичной границе
  - regression test: `tests/unit/services/schema_registry/test_typed_adapter.py`

#### Task E-5: A10 — 4 broken YAML call_function refs
- **Files:**
  - `extensions/credit_pipeline/workflows/credit_assessment.workflow.yaml`
  - `routes/hello_route/main.dsl.yaml`
  - `routes/test_route_w1/main.dsl.yaml`
  - `extensions/{core_admin,dadata,skb}/plugin.toml`
- **Diff:** ±20 LOC (либо restore функции, либо удалить broken refs)
- **Done criteria:**
  - 4 broken refs исправлены или удалены
  - `make plugin-schema validate` зелёный
  - regression test на каждый extension

#### Task E-6: A12 — hot-reload production wire
- **Files:** `src/backend/core/config/hot_reload.py:39-41` (call from lifespan)
- **Diff:** +15 LOC (вызвать `reloader.watch()` в app lifespan)
- **Done criteria:**
  - `hot_reload.watch()` вызывается в production lifespan
  - regression test на hot-reload через integration

#### Task E-7: A12 — ConsulConfigSettingsSource integrate
- **Files:** `src/backend/core/config/config_loader.py:273-303,347-353`
- **Diff:** +15 LOC (включить в `settings_customise_sources`)
- **Done criteria:**
  - Consul integration работает при `CONSUL_ENABLED=True`
  - regression test на Consul config loading

---

## 3. Stop-criterion verification

### Cycle 1 success criteria (по доменам):
- A11: 35% → **75-80%** (после 5 P0 + 4 P1 fixes)
- A8: 25% → **65-70%** (после 3 P0 из 6; остальные 3 P0 → cycle 2)
- A7: 65% → **75%** (после 3 P0 + cleanup)
- A2: 78% → **80-82%** (после 2 P0 + 1 P1)
- A1: 82% → **85%** (после 1 P0)
- A3: 73% → **78-80%** (после 2 P0)
- A5: 75% → **80%** (после 1 P0)
- A10: 77% → **80-82%** (после 4 P0)
- A12: 78% → **82-85%** (после 2 P0)
- A4: 95% → **96%** (без изменений, готов)
- A6: 80% → **82%** (после cross A8 fix B-3)
- A9: 66% → **70%** (без изменений в cycle 1, в cycle 2)

### Layer-allowlist target:
- Baseline: 180
- Cycle 1 target: **≤178** (−2 от cleanup)
- Если ≥180 → **блокирует завершение cycle**

### pip-audit allowlist:
- 35 active CVE — отдельный трек, не блокирует cycle 1
- Cycle 1 target: 8 stale CVE удалены → **27 active**

---

## 4. Параллельный execution plan

**7 параллельных групп разработчиков** (одна группа = один агент):

| Group | Domain | Tasks | Expected diff | Wall-clock estimate |
|---|---|---|---|---|
| **Группа A** | A11 | A-1, A-2, A-3, A-4, A-5 | +40 / −5 | 4-6 часов |
| **Группа B** | A8 | B-1, B-2, B-3 | +24 / −30 | 2-3 часа |
| **Группа C** | A7 | C-1, C-2, C-3 | +15 / −472 | 2-3 часа |
| **Группа D** | A2 | D-1, D-2, D-3 | +48 | 3-4 часа |
| **Группа E** | A1+A3+A5+A10+A12 | E-1..E-7 | +165 / −20 | 4-5 часов |

**Итого wall-clock:** max(Группа A..E) ≈ **6 часов** при параллельном выполнении.

**Конфликты между группами:**
- Группа B (A8 B-3) и Группа A10 (E-5) — оба трогают `extensions/core_entities/orders/`. Группа A10
  удаляет broken YAML refs, Группа B фиксирует `.then()` alias — **разные файлы**, можно параллельно.
- Группа A (A11) и Группа D (A2) — оба в infrastructure, но разные файлы, параллельно OK.

**Общий прогон:** `make lint && make type-check && make test -m 'not e2e' && make check-supply-chain`
после каждой группы, финальный прогон — после всех 5 групп.

---

## 5. Что НЕ входит в Cycle 1

### Перенос в Cycle 2:
- A8: D-A8-03 (ActivityBridge.decorate wire), D-A8-04 (TemporalWorkerPool wire) — крупные рефакторы
- A8: D-A8-06 (.then() alias — cross B-3, отдельная задача)
- A9: 3 P0 (RAG PII, dead prewarmer, hardcoded tenant_id)
- Оставшиеся 16 P0 из 29
- ~46 P1
- ~60 P2 (dead code)
- ~25 P3 (library replacements)

### Отдельные треки (не блокируют cycle 1):
- 35 active CVE в pip-audit allowlist (RESIDUAL, отдельный спринт)
- Layer-allowlist 180 → ≤100 (заявленная цель, требует dedicated cleanup PR)

---

## 6. Risk register

| Risk | Probability | Impact | Mitigation |
|---|---|---|---|
| `pip_audit_gate.py` change ломает CI | Medium | High | regression test в `tests/unit/tools/test_pip_audit_gate.py` |
| A11 SBOM regen ломает downstream consumers | Low | Medium | canonical path migration с symlink |
| A8 WorkflowFlags default change ломает workflows | Medium | High | regression test на все 4 флага, opt-in через feature flag |
| A7 `eip/reliability.py` removal ломает imports | Medium | Medium | grep verify перед удалением, фикс в одном PR |
| A3 admin fail-CLOSED ломает dev workflow | Low | High | dev profile override (fail-OPEN только в dev_light) |
| A10 broken YAML refs удаление ломает extensions | Medium | Medium | regression test на каждый extension перед удалением |

---

## 7. Definition of Done (cycle 1)

- [ ] 21 задача выполнена (группы A..E)
- [ ] Каждая задача имеет regression test
- [ ] `make format && make lint && make type-check` зелёный
- [ ] `make test -m 'not e2e'` зелёный (или известные failures документированы)
- [ ] `make check-supply-chain` зелёный (после фикса A11)
- [ ] `tools/check_layers.py` allowlist ≤ 178
- [ ] `.security/pip-audit-allowlist.txt` ≤ 71 строк (79 − 8 stale)
- [ ] Каждый security/data-loss фикс имеет docstring с маркером `"B-XX fix (cycle 1)"` или `"D-AUDIT-## fix (cycle 1)"`
- [ ] 5 git commits с conventional prefix + Russian-first messages, без emoji
- [ ] Phase 5 reviewer-gate (critic/architect/reviewer) → 3 PASS

**Если любой критерий НЕ выполнен → cycle 2 без пропуска фаз.**

---

## 8. Phase 4 launch plan

**5 параллельных агентов-разработчиков** (по группам A..E), каждый получает:
- Свой task list (A-1..A-5 / B-1..B-3 / C-1..C-3 / D-1..D-3 / E-1..E-7)
- Связанные файлы и ADR
- Stop-criteria (раздел 7)
- Правила (security markers, regression tests, NO force-push, NO new deps без CVE-check)

**Запуск через AgentSwarm** с `subagent_type="coder"`.

---

## 9. Phase 5 launch plan

**3 агента-ревьюера** (parallel):
- **Critic** (`subagent_type="explore"`): ищет скрытые TODO, тесты-моки, фиктивные закрытия
- **Architect** (`subagent_type="explore"`): прогон `tools/check_layers.py`, allowlist, layer discipline
- **Reviewer** (`subagent_type="coder"`): ruff/mypy/pytest на затронутых модулях

**Любой FAIL → cycle 2 без пропуска фаз.**

---

## 10. Команды для Phase 4 developer агентов

```bash
# Перед началом работы:
python tools/check_layers.py > cycle-1-baseline-pre.txt
cat .security/pip-audit-allowlist.txt | wc -l > cycle-1-cve-baseline.txt

# После работы:
make format && make lint && make type-check
make test -m 'not e2e' -k <test_path>
git add -p
git commit -m "<prefix>: <description> (B-XX fix (cycle 1))"

# Финальная проверка:
python tools/check_layers.py > cycle-1-baseline-post.txt
diff cycle-1-baseline-pre.txt cycle-1-baseline-post.txt
# Должно быть 0 новых violations
```

---

## 11. Финальный verdict Phase 3

Cycle 1 фокусируется на **P0 fixes для 9 доменов** + dead code cleanup. Этого достаточно для
**production sign-off** по security/data-loss рискам, но недостаточно для достижения 80% по всем
12 доменам (требуется cycle 2).

**Cycle 1 успех = закрытие production sign-off блокеров, не достижение 80% готовности по всем доменам.**

**Cycle 2 (отдельный трек) = достижение ≥80% готовности по всем 12 доменам.**

---

**Файл плана сохранён. Phase 3 завершена. Phase 4 готова к запуску.**
