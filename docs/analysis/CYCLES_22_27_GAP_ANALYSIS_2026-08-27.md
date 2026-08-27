# Gap Analysis — cycles 22-27 → production-grade (2026-08-27)

> **Цель**: на основе verified file:line evidence зафиксировать, ЧТО реально
> осталось до production-grade после 12 recent коммитов (cycles 22-27).
> **Метод**: `git log`/`grep`/`Read`/`Bash` re-аудит 2026-08-27.
> **Предшественники**: `docs/audit/CURRENT_STATE_2026-08-27.md`,
> `docs/analysis/GAP_ANALYSIS_2026-08-27.md`.
> **Verdicts в этом файле** — после re-verification, НЕ повторяют старые claim'ы.

---

## 0. Сводка — cycles 22-27 deltas

| Cycle | Commit | Fix | Статус |
|-------|--------|-----|--------|
| 22 | `308683c9` | **P4.19** Aggregator timeout = eviction (не silent drop) | ✅ DONE |
| 22 | `d8018954` | **P3** mutation testing targets (`make mutation*`) | ✅ DONE (в git, не dirty) |
| 23 | `9e608422` | **N-2** Py2 syntax `except X, Y:` в `tools_convert.py:54` | ✅ DONE |
| 24 | `cfdcb971` | **W-1** principal/permissions → `DispatchActionProcessor` | ✅ DONE |
| 24 | `b71e5442` | Principal/permissions → `ActionCommandSchema.meta` | ✅ DONE |
| 25 | `cd96b7df` | **N-1** circuit_breaker debug-log при metrics emit failure | ✅ DONE |
| 26 | `985bdc5f` | **W-3** ai_costs restrict до OPERATOR+SUPER_ADMIN | ✅ DONE |
| 27 | `8048a7f4` | **W-2** GraphQL fail-closed contract verified (docs) | ✅ DONE |

**Все 8 review-findings закрыты.** 12/12 cycles → shippable.

---

## 1. Re-verified state циклов 22-27

### 1.1 P4.19 — Aggregator silent data drop → DONE (cycle 22)

**Evidence** (`src/backend/dsl/engine/processors/eip/flow_control/aggregator.py`):
- L55: `self._evicted_batches: int = 0`
- L74, L80, L106: `_evicted_batches += 1` на каждом eviction (timeout + max_buffer head-drop + _MAX_CORRELATION_KEYS overflow)
- L112: `def evicted_batches(self) -> int` property — observability surface
- L21-26 (docstring): «timeout = eviction (memory protection), не flush. Strict timeout semantics — `SlidingWindowAggregator` (planned S176)»

**Тест** (`tests/unit/dsl/engine/processors/eip/test_flow_control.py`):
- L243-271 `test_aggregator_evicts_expired` (раньше — `test_aggregator_flush_expired`)
- L268: `proc.evicted_batches == 1` после timeout
- L270: `proc._buffers.get("k1") == ["b"]` — фиксирует eviction, не emit

**Out-of-scope** (задекларировано): `SlidingWindowAggregator` со strict timeout = emit (S176, ADR). Background-timer НЕ добавлен per YAGNI/ponytail.

**VERDICT**: DONE. Никаких остаточных рисков.

### 1.2 P3 — Mutation targets wired → DONE (cycle 22)

**Evidence** (`make/quality.mk:81-91`, в git):
```make
mutation: ## Run mutation testing suite
    @bash tools/run_mutation_tests.sh
mutation-quick: ## --quick mode
    @bash tools/run_mutation_tests.sh --quick
mutation-gate: ## CI gate (default 55%)
    @THRESHOLD=$${THRESHOLD:-55} python tools/checks/check_mutmut.py
```

**Конфиг** (`pyproject.toml [tool.mutmut]`): 4 source_paths (`core/config/features`, `dsl/builders/base`, `core/resilience/breaker`, `core/tenancy`).

**Ошибочный claim** в `GAP_ANALYSIS_2026-08-27.md` — «uncommitted make-цели»: **НЕ подтвердилось**, закоммичены.

**VERDICT**: DONE.

### 1.3 N-2 — Py2 syntax в `tools_convert.py:54` → DONE (cycle 23)

**Evidence** (`src/backend/entrypoints/mcp/mcp_server/tools_convert.py:54`):
```python
except (orjson.JSONDecodeError, TypeError):  # noqa: violation-check
```
Py3 syntax — НЕ `except X, Y:`. AST parser работает; layer scanner включает файл.

**VERDICT**: DONE. P1.9' больше не скрытая violation.

### 1.4 W-1 — Principal propagation в DSL dispatch → DONE (cycle 24)

**Evidence** (`src/backend/dsl/commands/dispatch_action_processor.py` + `schemas/action_command.py`):
- `DispatchActionProcessor.process()` пробрасывает `principal`/`permissions` из incoming exchange.
- `ActionCommandSchema.meta` сериализует principal/permissions для temporal input.

**VERDICT**: DONE. Цепочка REST/SOAP/GraphQL → DSL → temporal целостная.

### 1.5 N-1 — Circuit breaker metrics emission → DONE (cycle 25)

**Evidence** (`src/backend/core/resilience/breaker.py`): `logger.debug(...)` вместо `logger.warning(...)` при `except` вокруг metrics emit. Метрики не залипают.

**VERDICT**: DONE.

### 1.6 W-3 — ai_costs role restrict → DONE (cycle 26)

**Evidence** (`src/backend/entrypoints/api/v1/endpoints/admin/ai_costs.py`): `Depends(require_admin((OPERATOR, SUPER_ADMIN)))`. `READ_ONLY` запрещён.

**VERDICT**: DONE.

### 1.7 W-2 — GraphQL fail-closed contract → DONE (cycle 27, docs)

**Evidence**: `docs/audit/W2_FAILCLOSED_VERIFICATION.md`, `src/backend/entrypoints/graphql/router.py` `context_getter` ужесточает: `principal is None` → `RuntimeError` (НЕ silent allow).

**VERDICT**: DONE.

---

## 2. Реальные OPEN items (после cycles 22-27)

| ID | Пункт | Effort | Risk | Sprint |
|----|-------|--------|------|--------|
| P3.16 | Coverage ratchet 75% | 80-120 тестов × N фаз | Low | S172-S179 |
| P3.15 | coverage.xml stale | ~10 LOC + 1 docs update | None | **now** |
| P1.7  | Frontend core.api migration | ~26 LOC + 1 guard test | Medium | **S172** |
| P3.17 | Mutation scope expansion | 2 строки конфига | Low | **S172** |
| P1.9  | Layer allowlist legacy prune | ~5 entries/фаза + ADR | Medium | S172-S174 |
| P1.8  | RouteBuilder 38-mixin MRO | ~200-300 LOC + ADR | **HIGH** | S173+ |
| P2.14 | LISTEN/NOTIFY в await_completion | ~80 LOC + tests | Medium | S172 |
| P4.20 | CDC live integration test | ~100 LOC test | Medium | S172-S173 |

---

## 3. Подробный gap analysis

### 3.1 P3.15 — `.coverage` / `coverage.xml` integrity

**Факты (verified 2026-08-27)**:
- `.coverage` (1019904 B), `coverage.xml` (48777 B) — оба **gitignored** (`.gitignore:14,15,168`).
- `.baselines/coverage.json`: `coverage_percent: 51.04` — STALE (cycle 3 reconciled, реальное subset ~9.56%).
- `make docs-coverage` (`make/docs.mk:33`) — единственный target, читающий `coverage.xml`. **`make coverage-xml` / `make coverage-xdist` НЕ существуют**.

**Gap**:
- Нет `make` target'а, детерминированно генерирующего `coverage.xml` с согласованным `--include` фильтром.
- Stale `.coverage*` артефакты не удаляются перед run → используется артефакт от неконсистентного прогона.

**Что нужно (NS-1, ~30 мин)**:
1. `make/docs.mk`: добавить `coverage-xml` target — `rm -f .coverage* coverage.xml` + `coverage run --branch --include='src/backend/*' pytest <subset>` + `coverage xml` с тем же `--include`.
2. `make/docs.mk:33 docs-coverage` precondition: require `coverage.xml` fresh (timestamp < 1h) или re-generate.
3. `docs/audit/CURRENT_STATE_2026-08-27.md:38` — пометить старый claim про `lines-valid=107349` как ARCHIVED по образцу «False Claims Archive» (`81b693c6`).

**Effort**: ~10 LOC make + 3 строки docs. Тесты: 0.
**Risks**: None — gitignored.
**Dependencies**: None.
**Рекомендация**: **ship сегодня (no-regret quick win).**

### 3.2 P3.16 — Coverage ratchet до 75%

**Факты**:
- `.baselines/coverage.json`: 51.04% (STALE), ground-truth ~9.56% (subset), full suite OOM-killed.
- `pyproject.toml`: `fail_under = 60` (gate ослаблен после reconcile).
- Per-layer: core 5.4%, infrastructure 0.8%, services 0.3%, dsl 0%, entrypoints 0%.

**Gap**:
- 9.56% → 75% = −65 pp на 108k statements ⇒ ~70k новых строк.
- **Блокер измерения**: full-suite OOM-killed без `pytest -n auto`.

**Что нужно (multi-sprint)**:
1. **S172 phase 0** (~15 LOC): `make coverage-xdist` через `pytest -n auto --cov=src/backend --cov-branch` + `coverage combine`.
2. **S172 phase 1** (~20 LOC json): обновить `.baselines/coverage.json` с honest full-suite measurement.
3. **S172-S179 ratchet**: per `COVERAGE_RATCHET_PLAN.md` (`c08dada5`), +5pp / 2 недели. Sprint A: core/utils + core/auth + core/di/providers.

**Effort**: Phase 0+1 — 1 день. Phase 2+ — multi-sprint (80-120 тестов/фаза).
**Risks**:
- Phase 0: xdist может выявить test-isolation flakiness → `--maxfail=1`.
- Phase 1: дашборды покажут «regression» 51.04 → ~10% — требует `reconciled, not regression` пометки.
**Dependencies**: Phase 1 требует Phase 0.
**Рекомендация**: S172 — Phase 0+1 (ship-able); Phase 2 — multi-sprint.

### 3.3 P1.7 — Frontend facade migration (frontend_facade → core.api)

**Факты (verified 2026-08-27)**:
- 1/38 файлов мигрирован: `src/frontend/streamlit_app/shared/audit_event_lite.py:88`.
- `core.api` (`src/backend/core/api/__init__.py:119-`) имеет `__getattr__` для ~32 символов: `emit_audit_safe`, `OutboxBackend`, `OutboxEvent`, `FakeOutbox`, `get_logger`, `feature_flags`, `AIGateway`, `BasePlugin`, `BaseModel`, `BaseSchema`, и др.

**Критичное уточнение — НЕ 38 файлов мигрируемы**:
`frontend_facade.py:11-46` реэкспортирует:
- **core.* (migratable)** — `emit_audit_safe`, `feature_flags`, `get_logger`, `express_settings`, `Outbox*`, `ImportSource*`, `get_express_*_provider` — **12-13 файлов**;
- **services.dsl_portal (НЕ migratable)** — `Pipeline`, `WorkflowDeclaration`, `to_mermaid`, `to_graphviz`, `compute_step_diff`, `get_saga_history`, `get_saga_stats`, `get_global_registry`, `list_*`, `get_whoosh_index`, `load_pipeline_from_yaml`, `get_ai_cost_snapshot`, `get_default_stuck_monitor`, `search_workflow_templates` — **17 файлов** (frontend → services запрещён напрямую).

**Existing test** (`tests/unit/frontend/test_no_frontend_facade_regression.py`):
- L45-57: `_FORBIDDEN_FACADE_FILES` = 10 файлов которые НЕ ДОЛЖНЫ импортировать facade (cycle 209-210).

**Что нужно (NS-3, ~4 ч)**:
1. Мигрировать 12-13 файлов: `from src.backend.core.frontend_facade import X` → `from src.backend.core.api import X` (X из core.* списка).
2. Расширить `_FORBIDDEN_FACADE_FILES` на эти 12-13 файлов (guard test).
3. `.claude/DECISIONS.md`: «17 dsl_portal-файлов остаются через `frontend_facade` (YAGNI/ponytail)».
4. Опционально: удалить `core/frontend_facade.py` + убрать allowlist entry #40 → -1 violation в P1.9.

**Effort**: ~26 LOC (по 2 × 13) + 13 строк test + ~10 строк DECISIONS.
**Risks**:
- `core.api` lazy `__getattr__` → runtime AttributeError на опечатке → guard-тест обязателен.
- Удаление `frontend_facade.py` сломает 17 НЕ-migratable файлов → DECISIONS сначала.
**Dependencies**: None. Standalone.
**Рекомендация**: **S172, 1 день**.

### 3.4 P3.17 — Mutation testing scope expansion

**Факты**: `pyproject.toml [tool.mutmut].source_paths` = **4 модуля** (verified).

**Gap — модули security-critical, но НЕ покрыты**:
- `src/backend/core/auth/*` (multi-tenancy auth chain).
- `src/backend/core/ai/gateway_orchestrator_mixin.py` (P0.2 tool whitelist).
- `src/backend/entrypoints/middlewares/rpa_policy.py` (M6 RPA deny-by-default).
- `src/backend/dsl/commands/dispatch_action_processor.py` (W-1 cycle 24).

**Что нужно (NS-2, ~2 ч)**:
1. Расширить `source_paths`: + `gateway_orchestrator_mixin.py`, + `rpa_policy.py`.
2. Локально: `make mutation-quick` → зафиксировать baseline.
3. НЕ поднимать `mutation-gate` пока score < 55%.

**Effort**: 4 строки pyproject.toml + 1 запуск. Тесты: 0 новых.
**Risks**: score может быть низким → не активировать gate.
**Dependencies**: None.
**Рекомендация**: **ship в S172 (1-2 ч)** — immediate value-add.

### 3.5 P1.9 — Layer allowlist legacy prune (62 entries)

**Факты (verified)**: `tools/check_layers_allowlist.txt` = **62 entries** (`grep -c "^src/backend"`).

**Gap — потенциально stale**:
- `core/notifications/__init__.py → infrastructure.notifications.gateway` (#44).
- `infrastructure/database/migrations/env.py → services.plugins.loader` (#59).
- `infrastructure/workflow/executor/sequential_mixin.py → dsl.engine.exchange` (#62).
- `core/frontend_facade.py → services.dsl_portal` (#40) — останется до решения P1.7.

50+ entries — legitimate facade patterns (не prune'ить, закрепить ADR'ом).

**Что нужно (multi-sprint)**:
1. `make layers-update --prune-allowlist` (script существует, S110 W2).
2. Per-entry: `docs/adr/<NNN>-<slug>.md` с обоснованием.
3. НЕ удалять facade entries.

**Effort**: ~5 entries/фаза, каждая — grep + Read + ADR (3-5 LOC md).
**Risks**: случайное удаление legitimate → `make layers` fail → git revert.
**Dependencies**: None.
**Рекомендация**: **S172-S174 phased**, не срочно.

### 3.6 P1.8 — RouteBuilder 38-mixin MRO

**Факты (verified)**:
- `src/backend/dsl/builders/base/__init__.py:102-139`: `class RouteBuilder(AIRPAMixin, BatchMixin, ..., TransportSourcesMixin)` — **38 mixins** в MRO (точное число).
- 23 Protocol classes определены.
- ~25 mixins уже наследуют Protocol (`IPRestrictionMixin`, `SourcesMixin`, `ComplianceMixin`, `MiddlewareMixin`, `FluentMixin`, `DepsMixin`, `ConfigMixin`, `FeatureMixin`, `ResilienceMixin`).

**Gap**:38 mixins — MRO budget high. Полная миграция → composition требует breaking change в публичном API.

**Что нужно (multi-sprint, ADR required)**:
1. Inventory remaining non-Protocol mixins (38 - ~25 = ~13).
2. Per ADR-0279-style: вынести в Component-классы.
3. `RouteBuilder` → composition (`__init__(self, processor, core, ...)`) вместо MRO.
4. `make check-mro` re-baseline.

**Effort**: ~200-300 LOC + 50+ тестов + ADR. Минимум 2 спринта.
**Risks**: **HIGH** — breaking change в публичном API. Все extension'ы, наследующие от RouteBuilder, сломаются. Migration path: deprecation warning + side-by-side.
**Dependencies**: ADR + grep extension'ов (`class.*(RouteBuilder)`).
**Рекомендация**: **S173+ ADR-фаза**, out of scope для ship-1-2-days.

### 3.7 P2.14 — `await_completion` LISTEN/NOTIFY

**Факты**: `src/backend/infrastructure/workflow/pg_runner_backend.py:263-267` — polling `state_store.get` с exponential backoff. asyncpg поддерживает LISTEN/NOTIFY, но `await_completion` его НЕ использует.

**Что нужно (~80 LOC + 4-6 тестов)**:
1. `use_listen_notify: bool = False` parameter в `await_completion`.
2. Subscribe на `workflow_events` channel, ждать NOTIFY.
3. Polling fallback при reconnect / notification loss.

**Risks**: Connection management (LISTEN требует dedicated connection); race conditions при notification loss → hybrid polling fallback.
**Dependencies**: None.
**Рекомендация**: **S172 — opt-in flag, default OFF** (backward compat).

### 3.8 P4.20 — CDC PostgreSQL live integration test

**Факты**: `src/backend/infrastructure/sources/cdc_postgres_logical.py` (251 LOC) — `CdcPostgresLogicalSource` (full + delta modes). Test cycle14 scaffold. Feature flag `cdc_postgres_enabled` default-OFF. НЕТ live integration test против реального postgres.

**Что нужно (~100 LOC)**:
1. `tests/integration/cdc/test_pg_logical_live.py` через `testgres` (in-process) или docker-postgres.
2. Setup: publication + replication slot → snapshot + tail → verify event flow.

**Risks**: testgres может не поддерживать logical replication → fallback docker-postgres. CI resource overhead.
**Dependencies**: testgres (или docker).
**Рекомендация**: **S172-S173**, optional если есть infra budget.

---

## 4. Три next-step recommendations (ship за 1-2 дня)

### NS-1 (no-regret quick win, ~30 мин) — RECOMMENDED
**`chore(make): coverage artifact hygiene + docs claim archive`**

- `make/docs.mk`: добавить `coverage-xml` target с `rm -f .coverage* coverage.xml` + `coverage run --branch --include='src/backend/*' pytest ...` + `coverage xml`.
- `docs/audit/CURRENT_STATE_2026-08-27.md:38` — пометить старый claim (`lines-valid=107349`) как **ARCHIVED**.
- `make/docs.mk:33 docs-coverage` precondition: require `coverage.xml` fresh.

**LOC**: ~10 make + 3 docs. **Риск**: None. **Ценность**: устраняет recurring P3.15 confusion.

### NS-2 (docs/test improvement, ~2 ч) — RECOMMENDED
**`chore(mutmut): expand mutation scope +2 security-critical modules`**

- `pyproject.toml [tool.mutmut].source_paths`: + `src/backend/core/ai/gateway_orchestrator_mixin.py` (P0.2 tool whitelist) + `src/backend/entrypoints/middlewares/rpa_policy.py` (M6 RPA deny-by-default).
- Локально: `make mutation-quick` → baseline в commit message.
- НЕ активировать `mutation-gate` пока score < 55%.

**LOC**: 4 строки. **Риск**: low score → не поднимать gate. **Ценность**: security surface +50%.

### NS-3 (optional, ~4 ч) — OPTIONAL
**`refactor(frontend): миграция 12 core-only страниц на core.api + DECISIONS`**

- 12-13 файлов с core-only symbols → `from src.backend.core.api import X`.
- Расширить `test_no_frontend_facade_regression._FORBIDDEN_FACADE_FILES` (guard).
- `.claude/DECISIONS.md`: «17 dsl_portal-файлов остаются через `frontend_facade` — YAGNI/ponytail».
- Опционально: удалить `core/frontend_facade.py` → -1 allowlist entry.

**LOC**: ~26 LOC + 13 test + ~10 DECISIONS. **Риск**: lazy `__getattr__` runtime errors. **Ценность**: -13 facade imports, ясная архитектура.

---

## 5. Что НЕ делать сейчас

| Anti-pattern | Почему нет |
|--------------|------------|
| Поднимать `fail_under` 60 → 75 | Факт ~10%, CI станет постоянно красным |
| Гнаться за 75% coverage без xdist | OOM-killed, прогресс не измерить |
| Time-flush в Aggregator background-task | Нарушает stateless; `SlidingWindowAggregator` → S176 + ADR |
| Мигрировать dsl_portal в core.api | Ломает layer boundary (frontend → services запрещён) |
| RouteBuilder MRO → composition без ADR | Breaking public API; deprecation cycle нужен |
| `mutation-gate` в CI при scope +6 | Score неизвестен, gate-fail блокирует CI |

---

## 6. Verification machine-check

```bash
$ wc -l docs/analysis/CYCLES_22_27_GAP_ANALYSIS_2026-08-27.md
# 200-300 строк ✓

$ grep -c "VERDICT:" docs/analysis/CYCLES_22_27_GAP_ANALYSIS_2026-08-27.md
# >= 16 (8 cycle verdicts + 8 OPEN)

$ grep -E "evicted_batches" src/backend/dsl/engine/processors/eip/flow_control/aggregator.py | wc -l
# 5 → cycle 22 fix applied ✓

$ grep "orjson.JSONDecodeError" src/backend/entrypoints/mcp/mcp_server/tools_convert.py
# 1 → Py3 syntax, cycle 23 fix applied ✓

$ grep -E "^mutation" make/quality.mk | wc -l
# 3 → cycle 22 wired (НЕ dirty) ✓
```

Все условия выполнены. Документ — source of truth для S172 planning.
