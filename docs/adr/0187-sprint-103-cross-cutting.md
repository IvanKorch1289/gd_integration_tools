"""Sprint 103 closure — DEEP-RESEARCH follow-up: 4 cross-cutting items.

S103 = 4 cross-cutting items из S101 backlog + DEEP-RESEARCH.

**Sprint window:** S102 closure (2026-06-13) → S103 W5 (2026-06-13).
**Wave pattern:** 5 waves = 5 atomic commits.

---

## W1 — D5 extensions layer scanning (commit 33c096a5)

**Item:** DEEP-RESEARCH D5 (🔴) — extensions→infrastructure/services imports
(9 + 11 = 20 claimed violations).

**Honest measurement (per S58+ rule):** added extensions layer support
к linter, ran scan — **41 NEW violations** (выше заявленных 20).

**Solution:** `tools/check_layers.py` — `EXTENSIONS_LAYER` + `ALLOWED["extensions"] = {"core"}`.
Поддерживает 2 режима (`--root extensions` или `--root .`).

**Measured (D5 split-brain):**
- 5 extensions файлов: domain/models.py (ORM imports).
- 8 extensions файлов: repositories/* (imports base + session_manager).
- 16 extensions файлов: services/* (imports services + schemas).
- 12 extensions файлов: workflows/* (imports DSL).

**Total: 41 violations** (vs DEEP-RESEARCH claim 20). Honest scope:
detection only. Real fix (move models to core/) — multi-wave breaking
change, S103+ W2+ backlog.

---

## W2 — D9 cron_schedule DSL (commit done)

**Item:** DEEP-RESEARCH D9 (⚠️) — sub_workflow + cron_schedule missing.

**Solution:** NEW DSL method `RouteBuilder.cron_schedule()` + new processor
`CronScheduleProcessor` (dataclass, validation, kind="cron_schedule", to_dict).

**Files:**
- `src/backend/dsl/builders/integration_core/workflow_mixin.py` (+60 LOC).
- `src/backend/dsl/engine/processors/cron_schedule.py` (NEW, 90 LOC).
- `tests/unit/dsl/engine/processors/test_cron_schedule.py` (NEW, 9 tests).

**Validation:** 9/9 tests pass. Full validation (name, 5-field cron, workflow_name).

**Out of scope:** real Temporal Schedule-to-Close wiring (apscheduler adapter +
Temporal Schedule client) — multi-wave. W2 = facade pattern: DSL method
exists, real backend = future sprint.

---

## W3 — §3.4 Audit facade (commit done)

**Item:** DEEP-RESEARCH §3.4 (🟡) — 9 audit files split-brain.

**Honest measurement:** AuditService facade ALREADY exists (Sprint 16 W8,
ADR-0179 partial closure). 16 users migrated, 58 legacy `_emit_audit()`
callsites остаются.

**Solution:** `src/backend/core/audit/facade.py` (NEW, 70 LOC) — canonical
re-export of `AuditService` + `get_unified_audit_service` + new
`emit_audit()` sync wrapper (аналогично S95 W4 AuthGateway pattern).

**Files:**
- `src/backend/core/audit/facade.py` (NEW).
- `tests/unit/core/audit/test_facade.py` (NEW, 4 tests).

**Measured (audit consolidation):**
- Facade users: 16.
- Legacy `_emit_audit()` callsites: 58.
- Migration target: 100% facade by S105+ (multi-sprint).

**Out of scope:** migrate 58 legacy callsites. W3 = stable import path.

---

## W4 — V2 P0 #10 HTTP drain verification (commit 1cb55d8e)

**Item:** DEEP-RESEARCH V2 P0 #10 — HTTP drain ⏳.

**Honest measurement:** HTTP drain ALREADY implemented:
- uvicorn SIGTERM → lifespan shutdown → finally → `await ending()`
  (`lifespan.py:643`).
- HTTP/3: `serve_http3()` finally → `server.close()`
  (`server.py:98`).
- Worker drain: closed ранее (S86 W2).

**Solution:** `tests/unit/infrastructure/test_v2_p0_10_http_drain.py` (NEW,
87 LOC) — 6 regression-guard tests. Per S58+ rule — verification-only.

**Tests:** 6/6 pass. V2 P0 #10 fully verified closed.

---

## W5 — Closure (this ADR + CHANGELOG)

Final score:

| Item | S102 | S103 |
|------|------|------|
| D5 linter | ✗ blind | ✓ detects 41 violations |
| D9 cron DSL | ✗ missing | ✓ skeleton + 9 tests |
| §3.4 Audit facade | partial | ✓ canonical path + 4 tests |
| V2 P0 #10 HTTP drain | ⏳ | ✓ verified (6 tests) |
| Overall | 9.3 | **9.4** |

**5 commits, 4 cross-cutting items verified/addressed, score 9.3 → 9.4.**

Cumulative S93-S103: 11 sprints, 55 atomic commits, 247 NEW tests,
8 ADRs (0175-0187).
"""
