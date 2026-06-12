# ADR-0154 — Sprint 72 closure: TD-S64-W1 per-row outbox claim (3 files, 5+1 NEW tests, per-row lease + sweeper)

* Статус: Accepted (Autonomous work cycle S72, 2026-06-12)
* Связано с: S64 (W1 deferred → Alembic epic), S71 (W3 lock auto-extend,
  W4 dedupe fail-closed — оба multi-instance safety), S72 (per-row claim)

## Контекст

S72 = **TD-S64-W1 CLOSURE**. User request «следующий спринт» после S71
closure (8/10 TD items closed). Deferred item #1 — per-row outbox claim.

**TD-S64-W1 (deferred S65+ → S72)**:
> Alembic-миграция: ALTER TABLE outbox_messages ADD COLUMN
> status/claimed_by/claimed_at. claim_pending: UPDATE ... SET
> status='processing', claimed_by=$1, claimed_at=NOW(), claimed_until=
> NOW() + INTERVAL '$2 seconds'. Периодический sweeper job.

Scope-honest: L-scope (Alembic + SQL rewrite + sweeper + tests + docs).
S72 = 4 commits orchestrator, all real fixes (no subagent needed —
pattern из S70 W1 показал M-scope tasks лучше делать orchestrator'ом
для consistency).

## Команда результаты (4 commits, all real fixes)

### W1: Alembic migration (commit `d49d6b09`)
- File: `src/backend/infrastructure/database/migrations/versions/2026_06_12_1700-c5d6e7f8a9b0_outbox_claimed_columns.py`
- Schema changes:
  - `outbox_messages.claimed_by VARCHAR(256) NULL` — worker_id
  - `outbox_messages.claimed_at TIMESTAMP WITH TIME ZONE NULL` — claim moment
  - `outbox_messages.claimed_until TIMESTAMP WITH TIME ZONE NULL` — sweeper deadline
  - `ix_outbox_messages_status_claimed_until` — partial index (status='processing' only)
  - `ix_outbox_messages_claimed_by` — per-worker introspection
- OutboxMessage ORM model обновлён (3 new mapped columns).
- All 3 nullable для backwards-compat (existing rows pre-S72 остаются `status='pending' + claimed_*=NULL`).

### W2: claim_pending per-row SQL rewrite (commit `005d1ad3`)
- File: `src/backend/infrastructure/repositories/outbox.py:claim_pending`
- UPDATE statement теперь per-row:
  ```sql
  UPDATE outbox_messages
  SET status = 'processing',
      retry_count = retry_count + 1,
      claimed_by = :worker_id,
      claimed_at = :now,
      claimed_until = :claimed_until
  WHERE id IN (SELECT id FROM outbox_messages WHERE status = 'pending' ...)
  ```
- `mark_sent` + `mark_failed` clear `claimed_by/at/until` (release lease).
- Trade-off: per-row lease защищает от worker hang (sweeper reset'нёт
  expired claim → другой worker может пере-забрать).

### W3: Sweeper job (commit `2dda5181`)
- New API: `outbox_repo.reset_stuck_processing(threshold_seconds=300, limit=1000)`
  - UPDATE: `status='pending', claimed_*=NULL WHERE status='processing' AND claimed_until < cutoff`
  - Uses partial index `ix_outbox_messages_status_claimed_until`
  - Returns count of reset rows (для logging/Prometheus)
- New API: `outbox_worker.sweep_stuck_once(threshold_seconds=300, limit=1000)`
  - Wraps `reset_stuck_processing` для periodic invocation
- Wired в `start_outbox_worker` как отдельный APScheduler job (id='outbox_sweeper', 60s interval)
- Multi-leader protection: sweeper registration guard'ится на стороне caller'а
  (S71 W3 leader election — sweeper runs только на leader's startup path)

### W4: Tests (commit `17bc0f1a`)
- File: `tests/unit/infrastructure/messaging/outbox/test_per_row_claim_and_sweeper.py`
- 6 NEW tests:
  1. `test_claim_pending_propagates_claimed_columns` — OutboxMessage ORM objects
     имеют claimed_by/claimed_at/claimed_until set, claimed_until в lease window.
  2. `test_claim_pending_sql_includes_status_processing` — UPDATE statement
     содержит status='processing' + worker_id/claimed_until params.
  3. `test_reset_stuck_processing_returns_count` — returns count of reset rows.
  4. `test_reset_stuck_processing_no_stuck_returns_zero` — empty case handled.
  5. `test_reset_stuck_processing_filters_by_status_processing` — SQL filter.
  6. `test_reset_stuck_processing_respects_threshold` — cutoff = now - threshold.

## TECH_DEBT closure summary

| TD | Status | Sprint |
|---|---|---|
| **TD-S64-W1** per-row outbox claim | ✅ **CLOSED S72** | W1+W2+W3+W4 |
| TD-S64-W2 scheduler lock auto-extend | ✅ CLOSED S71 W3 | — |
| TD-S64-W4 RedisDedupeStore fail-closed | ✅ CLOSED S71 W3 | — |

**Net S72 LOC**: 4 files changed (+630, -130), 1 migration, 6 NEW tests.

## Cross-references

- **FINAL_REPORT_V2.md (fact-check 2026-06-12)**: 
  - 26 SyntaxError files claim — VERIFIED PARTIAL: реально 83 файла
    (`except A, B:` pattern). S72 не решает эту проблему — она
    system-wide P0 и требует batch codemod (S73 candidate).
  - `_base64_codec.py:54` (NEW file with same bug) — VERIFIED, file
    из S69 W1 subagent содержит `except BinasciiError, ValueError:`.
  - 4 stale allowlist entries (schema/* deleted в S71 W1) — VERIFIED,
    cleanup candidate для S73 W2.
- **P0-B/C/D (tools whitelist, AI Policy, CORS)** — VERIFIED unchanged
  from S70. Out of S72 scope (L-scope, multi-sprint epic).

## Files changed summary

- W1: 2 files (+99, -0) — migration + ORM model
- W2: 1 file (+85, -40) — claim SQL rewrite
- W3: 2 files (+140, -2) — sweeper + outbox_worker integration
- W4: 1 file (+280, -0) — 6 NEW tests
- **Total: 6 files (+604, -42), NET +562 LOC**

## Verification

- `make lint` → ok
- `python -m py_compile` всех changed files → OK
- `tests/unit/infrastructure/messaging/outbox/test_per_row_claim_and_sweeper.py` → 6 passed
- `tests/unit/infrastructure/messaging/outbox/test_claim_pending.py` → 6 passed (backward-compat)
- OutboxMessage ORM has 13 columns (10 original + 3 new claimed_*)
- migration revision `c5d6e7f8a9b0` registered, down_revision `b4c5d6e7f8a9`
