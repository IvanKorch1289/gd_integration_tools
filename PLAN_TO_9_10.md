# План доработки до 9/10 — gd_integration_tools

> **Методология:** "Изучи отчёт + проведи циклы доработки до 9.0/10"
> Сгенерировано на основе DEEP_AUDIT_REPORT.md (22.06.2026), KNOWN_ISSUES.md
> (04.08.2026) и моего L1 pure ASGI consistency project (26 cycles, cycles 33-58).

---

## Executive Summary

DEEP_AUDIT_REPORT от 22.06.2026 дал такие оценки компонентов:

| Компонент | Текущая | Цель | Δ |
|---|---|---|---|
| **Architectural Maturity** | 7/10 | **9/10** | +2 |
| **Extensibility** | 6/10 | **9/10** | +3 |
| **Production Readiness** | 7/10 | **9/10** | +2 |
| **DSL Completeness** | 8/10 | **9/10** | +1 |
| **Agent Safety** | 4/10 | **9/10** | +5 |
| **Docs Maturity** | 8/10 | **9/10** | +1 |
| **Maintainability** | 6/10 | **9/10** | +3 |
| **ИТОГО** | **~6.6/10** | **9/10** | +2.4 |

**Уже сделано в циклах 33-58 (45 атомарных коммитов):**
- ✅ Все 23 L1 middlewares переписаны на pure ASGI (100% L1 consistency)
- ✅ 3 реальных bug fix'а: B-02 CDC event loss, B-04 hot_swap, B-07 SecurityHeaders
- ✅ 248+ новых unit-тестов (все pure ASGI regression-тесты)
- ✅ L1 layer готов для production deploy

**Критическая нота (подтверждено в KNOWN_ISSUES.md):**
> Аудит-отчёты устаревают за 1-2 спринта. Перед планированием работы
> над любым P0/P1 — **грепнуть актуальный код**, не доверять только
> записям журнала. Этот план фокусируется на **реально актуальных**
> проблемах (verified by code grep), не на historical находках.

---

## Phase 1: Stabilization (Horizon 2) — 12-15 cycles (target 7/10 → 8/10)

**Цель:** закрыть 11 remaining items из J. REFACTORING ROADMAP (P10-P18, P6, P7).

### 1.1. Security Hardening (cycles 59-64, 6 cycles)

| ID | Item | Cycle | Scope |
|---|---|---|---|
| **P11.1** | SOAP auth: добавить auth middleware | 59 | `entrypoints/soap/` (если существует) или skip |
| **P11.2** | GraphQL auth: `AuthGuardMiddleware` для `/graphql` | 60 | `entrypoints/graphql/` (2-3 файла) |
| **P11.3** | SSE auth: `BearerTokenRequiredMiddleware` для `/sse/*` | 61 | `entrypoints/sse/` (cycle 45 audit_replay pattern) |
| **P14** | Bulk operations batch limits | 62 | Redis `bulk_get/set` + ClickHouse `insert` (cycle 19: redis_client.py + ch_client.py) |
| **P16** | fs_facade symlink race | 63 | `core/ai/fs_facade.py` (cycle 2 retro: уже fixed, verify) |
| **P17** | yaml.safe_load в codegen_settings | 64 | `tools/codegen_settings.py:656` (cycle 2 retro: grep для 0 вхождений) |

**Cycle 59-61 invariant:** используем cycle 43/45/47 pattern — pure ASGI middleware
с `send_wrapper` для status capture + no-raise для auth failures.

### 1.2. Performance (cycle 65-66, 2 cycles)

| ID | Item | Cycle | Scope |
|---|---|---|---|
| **P15.1** | Wrap `os.walk` in `asyncio.to_thread` | 65 | `dsl/engine/processors/file_watch.py` (cycle 2 retro: fixed) |
| **P15.2** | Spec hot-reload caching | 66 | `dsl/engine/spec_loader.py` — cache compiled specs (cycle 12 P5 паттерн) |

### 1.3. Cleanup (cycle 67-68, 2 cycles)

| ID | Item | Cycle | Scope |
|---|---|---|---|
| **P18** | Удалить duplicate `MetricsRegistry` | 67 | `infrastructure/observability/metrics.py` (cycle 2 retro: 0 duplicates) |
| **P9-verify** | Удалить оставшиеся 172 layer violations allowlist | 68 | `tools/check_layers_allowlist.txt` (172 → 0 за N итераций) |

**Cycle 67 invariant:** Перед удалением grep для других ссылок.
Cycle 68 invariant:** Каждое удаление layer violation — атомарный
коммит с regression test.

### 1.4. Layer Violations (cycle 69-72, 4 cycles)

| ID | Item | Cycle | Scope |
|---|---|---|---|
| **P6.1** | Frontend → `core.api` facade | 69-70 | `src/frontend/streamlit_app/` (35+ файлов) |
| **P6.2** | Extensions → `core.api` facade | 71-72 | `extensions/{core_entities,credit_pipeline,osint_agent,skb}/` |

**Cycle 69-72 invariant:** Создаём `src/backend/core/api/{ai,auth,workflow,config}.py`
как thin re-exports. Каждый frontend/extension файл мигрирует
по одному, не блокируя другие.

### Итог Phase 1: ~6.6/10 → ~7.8/10 (если cycle 2 retro подтвердит что P16/P17/P18 уже fixed)

---

## Phase 2: Platform Evolution (Horizon 3) — 8-10 cycles (target 8/10 → 9/10)

**Цель:** закрыть 6 remaining items (P19-P24), достичь оценки 9/10.

### 2.1. Agent Safety (cycle 73-77, 5 cycles)

**Cycle 73 — P19.1: Deprecate InProcessAgentSandbox (2-phase)**
- Phase 1: Добавить `DeprecationWarning` если `InProcessAgentSandbox` используется в production
- Phase 2: Удалить из `services/ai/agent_sandbox.py`
- Estimate: 2-3 файла, 1 cycle

**Cycle 74 — P20: Token budget enforcement**
- Новый `core/ai/token_budget.py` с `TokenBudget` Protocol
- Интеграция в `AIGateway.invoke` (проверка budget ДО invocation)
- Estimate: 1 файл + tests

**Cycle 75 — P21: Create `core/api` facade**
- `src/backend/core/api/{ai,auth,workflow,config}.py` — thin re-exports
- Каждый public class в core реэкспортируется
- Estimate: 4-5 файлов

**Cycle 76 — P22: Complete CDC PostgreSQL implementation**
- Cycle 33 уже fixed B-02. P22 — extend `debezium_events_backend.py`:
  - Добавить offset tracking (cycle 24 CDC pattern)
  - Интеграция с Kafka consumer group
- Estimate: 1 файл

**Cycle 77 — P23: Replace HITL busy-wait with pub/sub**
- Cycle 17 уже added Cycle 23 P23. Cycle 77: добавить тесты + finalize
- Новый `core/ai/hitl/pubsub_backend.py` для async pub/sub
- Estimate: 1 файл + tests

### 2.2. Tool Enforcement (cycle 78, 1 cycle)

**Cycle 78 — P24: Wire AIPolicySpec tools enforcement**
- Cycle 36 уже verified. Cycle 78: добавить test для конкретного кейса (e.g., agent tries to use `shell` tool without permission)
- Estimate: 1 cycle

### 2.3. Documentation Hardening (cycle 79-80, 2 cycles)

**Cycle 79 — ADRs completeness**
- Проверить все 27 ADRs (cycle 1-26) на актуальность
- Добавить недостающие ADRs для cycle 27-58 (L1 pure ASGI migration)
- Estimate: 1 cycle

**Cycle 80 — Tutorial / Runbook completeness**
- Проверить `docs/tutorials/` и `docs/runbooks/`
- Добавить tutorial для pure ASGI middleware pattern (cycle 36-58)
- Estimate: 1 cycle

### Итог Phase 2: 7.8/10 → 8.5/10 (если cycle 2 retro не покажет P19/P22 как уже-fixed)

---

## Phase 3: Refinement (Final 9/10 polish) — 5-7 cycles

**Цель:** довести каждый компонент до 9/10.

### 3.1. RouteBuilder Refactor (cycle 81-83, 3 cycles)

Cycle 81: Extract 5 RouteBuilder mixins (cycle 9 MRO analysis)
Cycle 82: Add per-mixin test suites (бывшие 325 рёбер в графе → manageable)
Cycle 83: Add cycle_2 retro verification

### 3.2. WorkflowBuilder Migration (cycle 84, 1 cycle)

Cycle 84: Удалить deprecated `WorkflowBuilder`, перевести все callers
на Single-Entry pattern (cycle 2 retro: проверить что нет active callers)

### 3.3. Security Audit Pass (cycle 85, 1 cycle)

Cycle 85: Cycle 2 retro на все 35+ layer violations в `src/frontend/`
— проверить что они перенесены в `core.api` imports (cycle 69-72)

### Итог Phase 3: 8.5/10 → 9/10

---

## Итоговый timeline (cycles 59-85, ~27 cycles × 30min average)

| Phase | Cycles | Goal | Expected Final Score |
|---|---|---|---|
| **Phase 1** (Security + Performance + Cleanup) | 59-68 (10 cycles) | Stabilization | 7.0/10 → 7.8/10 |
| **Phase 1.4** (Layer Violations) | 69-72 (4 cycles) | Layer hygiene | 7.8/10 → 8.2/10 |
| **Phase 2** (Platform Evolution) | 73-80 (8 cycles) | Agent Safety + Docs | 8.2/10 → 8.7/10 |
| **Phase 3** (Refinement) | 81-85 (5 cycles) | Polish | 8.7/10 → **9.0/10** |

**Total: ~27 cycles = 13-15 часов** (в single-agent session непрерывно).

---

## Critical Methodology Notes (из L1 cycles 33-58)

1. **Verify before plan:** Перед каждым cycle — grep для actual состояния.
   Многие находки в `DEEP_AUDIT_REPORT.md` от 22.06.2026 уже fixed
   в текущем master (KNOWN_ISSUES.md это документирует).

2. **Cycle 2 retrospective:** Каждый cycle имеет cycle 2 retro —
   находим fragile patterns в написанных тестах (например,
   monkeypatch path, missing fixtures, byte-count assertions
   с spaces).

3. **Atomic commits + regression tests:** Каждый cycle = 1 commit +
   tests. Tests fail при повторном "фиктивном закрытии".

4. **Compound lessons:** L1 cycles 33-58 накопили 23 lessons
   (send-wrapper pattern, no-raise rule, state-modification-order,
   и т.д.). Эти patterns применимы к Phase 1-3.

5. **TestClient compatibility:** Phase 1.4 (layer violations) — 
   TestClient auto-совместим с pure ASGI middleware (как cycle 56 retro
   показал).

---

## Risk Assessment

| Risk | Probability | Impact | Mitigation |
|---|---|---|---|
| P19 InProcessAgentSandbox removal breaks existing code | MEDIUM | HIGH | 2-phase removal: warning first, removal second |
| Frontend layer violations (35+ files) | LOW | MEDIUM | Cycle 69-70 — atomic per file |
| Token budget breaking existing flows | LOW | MEDIUM | Cycle 74 — feature-flag default OFF |
| Pub/Sub backend не совместим с existing HITL | MEDIUM | MEDIUM | Cycle 77 — keep old busy-wait as fallback |
| RouteBuilder refactor breaks workflows | HIGH | MEDIUM | Cycle 81-82 — gradual extraction |

**Overall risk level:** MEDIUM. Mitigations в place через cycle 2
retrospective pattern.

---

## Honest Assessment

**Goal "all parts to 9.0/10" in single agent session: ACHIEVABLE but TIGHT.**

С 27 cycles (13-15 часов) можно довести до 9.0/10 при условии:
- Cycle 2 retro подтвердит что P10, P13, P16, P17, P18, P22 уже
  реализованы (что соответствует KNOWN_ISSUES.md)
- Phase 1 + Phase 2 + Phase 3 пройдут без regression issues
- L1 layer (100% pure ASGI) будет стабильным фундаментом

**Если cycle 2 retro покажет что больше P0/P1 уже fixed** —
можно сократить план на 30% (только Phase 2 + Phase 3, ~13 cycles
вместо 27).

**Ожидаемый final score:** 8.8-9.2/10 (если все assumptions верны),
7.5-8.0/10 (если появятся regressions при dependency changes).

---

## Следующие шаги

Cycle 59 — начать Phase 1.1 (Security Hardening): P11.1 SOAP auth.
Перед cycle: grep `find src/backend/entrypoints -name "soap*"` чтобы
проверить существует ли SOAP entrypoint (если нет — skip to P11.2
GraphQL auth).

Каждый cycle должен следовать паттерну:
1. Verify (grep, read код)
2. Plan (1-2 файла, atomic change)
3. Implement (code + tests)
4. Test (run pytest, fix cycles 2 retro)
5. Commit (atomic, with descriptive message)
6. Update KNOWN_ISSUES.md (если находка была significant)

Готов к старту Phase 1.
