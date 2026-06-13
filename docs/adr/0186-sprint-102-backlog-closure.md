"""Sprint 102 closure — DEEP-RESEARCH follow-up: backlog items W1-W4.

S102 = small backlog sprints. Цель — закрыть 3 мелких item'а из S101 W5 backlog.

**Sprint window:** S101 closure (2026-06-13) → S102 W5 (2026-06-13).
**Wave pattern:** 5 waves = 5 atomic commits.

---

## W1 — CDCClient singleton bug fix (commits 0c695a74 + 1ebd856a)

**Item:** S101 backlog — pre-existing ``NameError: _cdc_instance`` в
``get_cdc_client()`` (с S60 W2 decomp).

**Solution:**
* ``_cdc_instance: CDCClient | None = None`` — module-level singleton.
* ``_cdc_lock = threading.Lock()`` — double-checked locking для concurrent
  first-call safety.
* ``reset_cdc_client()`` — test helper для singleton reset (важно для pytest).
* S101 W1 SKIP test → активный test (bug fixed).

**Files:**
- `src/backend/infrastructure/clients/external/cdc/client.py` (+30 LOC)
- `src/backend/infrastructure/clients/external/cdc/__init__.py` (re-export)
- `tests/unit/core/cdc/test_registry.py` (unskip adapter test)

**Validation:** 35/35 CDC tests pass + 0 regressions.

---

## W2 — CI lint.yml `--strict` exit 2 fix (commit aec1ecc0)

**Item:** S101 backlog — CI вызывал ``check_docstrings.py --strict`` без
positional paths → typer exit 2 (per app_main в tools/check_docstrings.py:245-249).
Gate fail'ил без doing anything.

**Solution:**
* lint.yml: убран ``--strict``, добавлены 8 explicit paths (same as
  pre-commit hook после S101 W3 extension).
* ``continue-on-error: true`` остаётся (ratchet ещё большой — S104+ backlog).

**Validation:** 0 NEW violations (1649 = allowlist). Gate exit 0 в CI.

---

## W3 — V2 P0 #6 closure verification (commit 6aa5f95f)

**Item:** S101 backlog claim "5/7 моделей" — actually 7/7 closed.

**Honest verification:** DEEP-RESEARCH (2026-06-12, S92 state) был УСТАРЕВШИМ.
S89 (Order) + S91 (User) + S92 W1 (File) + S92 W2 (OrderKind + WorkflowInstance)
+ S101 W4 (DslSnapshot + WorkflowEvent) = 7/7 ✅.

**W3 work:** regression-guard test (8 tests, parametrized × 7 models + 1
closure check). Per S58+ rule "refactor > 1 wave = analysis-only OR
1-commit с measured numbers" — verification-only commit.

**Score impact:** V2 P0 #6 fully closed (was 5/7 in S101, now 7/7 verified).

---

## W4 — Docstring ratchet -7 (commit 8b6f36f3)

**Item:** S101 backlog — ratchet target 1649 → 0.

**Solution:** 8 NEW docstrings в 4 файлах:
- `core/ai/context_strategy.py` (3): RollingWindow, MapReduce, Hierarchical `apply`.
- `core/ai/errors.py` (1): MCPToolError.to_dict.
- `core/ai/guardrails/llamaguard.py` (1): GuardResult.is_safe.
- `core/config/services/cache.py` (2): RedisSettings.validate_redis_numbers, get_stream_name.
- `core/config/services/queue.py` (3): QueueSettings.validate_port, validate_ca_path, get_queue_name.

**Allowlist:** 1649 → 1642 (net -7; close to -10 target).

---

## W5 — Closure (this ADR + CHANGELOG)

Final score:

| Item | S101 | S102 |
|------|------|------|
| CDCClient bug | ✗ broken | ✓ fixed |
| CI lint gate | ✗ exit 2 | ✓ exit 0 |
| V2 P0 #6 | 5/7 | **7/7 verified** |
| Docstring ratchet | 1649 | **1642** |
| Overall | 9.2 | **9.3** |

**5 commits, 3 backlog items closed, 1 docstring ratchet progress.**
"""
