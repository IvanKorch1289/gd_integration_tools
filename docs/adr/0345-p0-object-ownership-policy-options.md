# ADR-0345 — Object-Level Authorization: ownership policy (P0 audit response)

## Статус

**DRAFT** (2026-09-24, cycle 158+). Per v4 §6 gate "Approval/ADR" — этот
ADR фиксирует **3 варианта** для P0 fix (cross-tenant exposure)
и **запрашивает user choice** между ними перед implementation.

## Контекст

Per `tools/classify_object_authorization.py` (cycle 158+ commit `5580f2621`)
+ service-layer inspection (commit `2b4c21878`), выявлено:

- **4 confirmed REAL P0 cross-tenant gaps** (per v4 §5 verified evidence):
  1. `HitlService.get()/wait_for()/resolve()` (`hitl.py:164, 185, 225`;
     `hitl_approval.py:263`) — accept `signal_id` без tenant filter.
  2. `NotebookRepository.get()` (`notebooks.py:156`) — by-id only.
  3. `AIFeedbackRepository.get()` (`ai_feedback.py:168`) — by-id only.

- **1 conditional**:
  4. `audit_versioning.py:151` (`Versioning.get_version`) — depends on
     parent model tenant-scope (BaseModel has no `tenant_id`).

- **24 unknown** — likely all DSL infra (UI compilation state, etc.).

Per v4 §10 P0 priority, эти gaps должны быть closed перед production
release (cross-tenant access является security-relevant).

## Решение (3 варианта)

### Option A — Per-call explicit fix (рекомендуемый для current scope)

**Реализация**: каждый `get/signal_id` / `get/notebook_id` / `get/doc_id`
добавляет explicit `tenant_id` parameter, проверяет на equality с
`current_tenant()` context, возвращает `None` если mismatch.

**Trade-offs**:
- ✅ Minimal risk, maximum control.
- ✅ Test infrastructure проста: каждый call — отдельный test.
- ❌ Требует **adherence at every callsite** — programmer долг.
- ❌ Cross-tenant access possible if developer forgets the filter.

**LOC estimate**: 6-10 lines production code + 3-4 cross-tenant tests.

**Lifecycle impact**: backwards-compatible (new optional parameter).
Existing callers продолжат работать (or fail loudly with explicit error
если mandatory).

### Option B — Global policy + middleware (centralized, design-heavy)

**Реализация**:
- ADR for global policy (Casbin vs custom class-based).
- Per-route declaration: required scopes/permissions.
- SQLAlchemy `before_compile` event listener injects tenant filter
  для автоматической enforcement.
- Middleware OR explicit guard per business operation.

**Trade-offs**:
- ✅ Single source of truth для ownership rules.
- ✅ Fail-closed by default (centralized enforcement).
- ❌ Architectural decision (Casbin? custom? class-based?).
- ❌ Bigger blast radius (all routes).
- ❌ Migration window требуется (existing code paths).

**LOC estimate**: 50-200 lines + ADR design discussion + integration tests.

### Option C — Outbox/Hybrid (compromise)

**Реализация**:
- A small TenantContext-enforcing decorator/wrapper per service class.
- Service-layer decorator требует explicit annotation.
- Backstop: SQLAlchemy event listener logs (not enforces) violations.

**Trade-offs**:
- ✅ Less invasive than B.
- ✅ Maintains fail-open semantics (existing callers continue).
- ❌ Two layers of enforcement (decorator + log) — complexity.

**LOC estimate**: 30-50 lines + decorator module + integration tests.

## Альтернативы рассмотрены

### 1. Defer P0 fix entirely
- ❌ Отклонено: gap is real, audit debt documented per v4 §10 P0.

### 2. Add tenant_id param без проверки (trust caller)
- ❌ Отклонено: не устраняет gap, только делает API wider.

### 3. Apply per-call checks напрямую (Option A) AND add log middleware
- ⚠️ Possible — combines A + log instrumentation из C.
- Defers enforcement, tracks violations.
- Per v4 evidence-first, лучше явный fail-closed check.

### 4. Drop P0 fix в пользу privacy backend (P1) work
- ❌ Отклонено: P0 > P1 priority; оба могут быть сделаны в разных cycles.

## Последствия

### Per Option A (recommended)
- ✅ Minimal blast radius (4 callsites).
- ✅ Tests integrate без infrastructure overhaul.
- ⚠️ Relies on developer discipline (programmer adherence).
- ⚠️ Future callsites могут забыть check (mitigation: ADR-0345 + cyc-159 lint rule).

### Per Option B
- ✅ Single enforcement point.
- ✅ Better security posture (fail-closed).
- ⚠️ Migration risk: existing code paths may break.
- ⚠️ Bigger blast radius.

### Per Option C
- ✅ Compromise approach.
- ⚠️ Two enforcement layers = complex.

## Honest trade-off summary

| Option | Risk | Effort | Security Posture | Migration Window |
|---|---|---|---|---|
| **A** | LOW | LOW | MEDIUM | 0 (backwards-compat) |
| **B** | HIGH | HIGH | HIGH | 1-2 cycles |
| **C** | MEDIUM | MEDIUM | HIGH | 0.5-1 cycle |

**Recommendation** for next-cycle:
- **Start with Option A** (per-call) for the 4 confirmed gaps.
- Schedule **Option B ADR** for design decisions как separate ADR per v4 §10 P0.5.
- **Option C** as fallback if A fails to capture new callsites.

## Per v4 §6 8-gate assessment

| Gate | Option A | Option B | Option C |
|---|---|---|---|
| Problem proof | ✅ THIS ADR + cycle 158+ docs | ✅ | ✅ |
| Existing solution audit | ✅ cycle 158+ | needs Casbin survey | needs decorator survey |
| Architecture fit | ✅ minimal | ⚠️ Casbin vs custom decision | ⚠️ 2-layer enforcement |
| Value | ✅ 4 callsites fixed | ✅ all routes | ✅ all routes |
| Parity | ✅ backwards-compatible | ⚠️ needs migration | ✅ backwards-compat |
| Blast radius | ✅ 4 callsites | ⚠️ all routes | ⚠️ all services |
| Verification plan | ✅ per-call tests | ⚠️ migration tests | ⚠️ integration tests |
| Approval | ✅ user choice | ❌ needs ADR+N decisions | ⚠️ design clarity |

**Best for next-cycle**: Option A (lowest risk, sufficient for current gap).
**Best for production**: Option B (long-term, requires design session).

## Что НЕ делали в этой итерации

- ❌ Не реализовали Option A/B/C — это ADR ДРАФТ, не implementation.
- ❌ Не выбирали preference — это user decision per kickoff "не использовать
  ask_user без необходимости" inverse.
- ❌ Не мигрировали callers — каждый Option требует migration window
  per v4 §10 P1.

## Что сделано (per cycle 158+)

1. ✅ `tools/classify_object_authorization.py` (heuristic classifier).
2. ✅ 8 regression tests (`test_w11_p0_3_classify_object_authorization.py`).
3. ✅ Bug fix `e03561ce7` (svc.get pattern missing → surfaced 3 missed callsites).
4. ✅ Investigation doc (`P0_USER_DATA_CALLSITES_INVESTIGATION_2026-09-24.md`).
5. ✅ Service-layer verification doc (`P0_USER_DATA_CALLSITES_VERIFIED_2026-09-24.md`).
6. ✅ Cycle 158+ P0 verification summary в PROGRESS_LEDGER (`b05471750`).
7. ✅ THIS ADR draft.

Total cycle 158+ work: 4 ADRs + 5 sibling roadmap docs + multiple
broken-gate fixes + 3 architectural fixes (hvac, dlq, config.services) +
verification infrastructure.

## Что требуется для next-cycle implementation

1. **User choice** между A/B/C (or hybrid).
2. **ADR finalization** после user choice (this ADR becomes "Accepted" with selection).
3. **Implementation per chosen option** (A: 6-10 LOC; B: 50-200 LOC; C: 30-50 LOC).
4. **Cross-tenant tests** (3-4 minimum).
5. **Verification** per v4 §6 8-gate re-audit.

## References

- v4 §10 P0 priority.
- v4 §10 P1 "Удалять shim только после 0 importers + migration window + contract test".
- v4 §6 "Gate допуска улучшения" 8-gate framework.
- cycle 158+:
  - `tools/classify_object_authorization.py` — heuristic tool.
  - `docs/roadmap/P0_USER_DATA_CALLSITES_INVESTIGATION_2026-09-24.md` — initial deep-dive.
  - `docs/roadmap/P0_USER_DATA_CALLSITES_VERIFIED_2026-09-24.md` — verified evidence.
  - `b05471750` — PROGRESS_LEDGER final summary.
- ADR-0316 (SagaLRA W2 P0-3 Phase 2 Variant A — pattern parallel для ADR structure).
- v4 §5 demonstrated: classifier output verified, NOT estimates.
