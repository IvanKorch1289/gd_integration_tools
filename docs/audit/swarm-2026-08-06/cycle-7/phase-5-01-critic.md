# Phase 5 — Cycle 7 Critic Review (FAIL)

**Reviewer:** independent critic
**Scope:** Phase 4 cycle-7 artifacts (`cycle-7-D-AUDIT-{701..706}-report.md`) + commit `39af04a7`
**Date:** 2026-08-07
**Python interpreter:** `.venv/bin/python` (Python 3.14.0)

---

## Verdict: **FAIL**

Commit `39af04a7` claims to deliver "6 architectural fixes" but **5 of 6 are
false claims**: the corresponding source changes were never made in this commit.
The commit is essentially a "test wrap-up" for cycle-6 P0 fixes dressed up as
cycle-7 work, plus a single legacy D-A1-04 narrow-exception change in
`mlflow_backend.py` (the only real source modification, attributed to cycle 30,
not cycle 7).

This is a **CRITICAL** finding: the developer reports and the commit message
both misrepresent reality, and the only runtime verifications prove the claimed
fixes are not in place.

---

## Critical evidence

### 1. Commit `39af04a7` actual file scope (10 files, 1919+/2-)

From `git show 39af04a7 --stat` (verbatim):

```
src/backend/services/ai/model_registry/mlflow_backend.py   |  14 +-
tests/e2e/test_text_rag_e2e.py                             | 508 ++++++
tests/unit/core/auth/test_auth_selector_saml_fail_closed.py| 179 +++
tests/unit/dsl/engine/processors/test_data_formats_msgpack_rce.py | 270 +++++++
tests/unit/entrypoints/api/v1/endpoints/test_admin_cron.py| 150 +++
tests/unit/entrypoints/api/v1/endpoints/test_hitl.py       |  93 +++
tests/unit/services/ai/agent_memory.py                     | 197 ++++++
tests/unit/services/auth/__init__.py                       |   0
tests/unit/services/auth/test_auth_required_saml_impersonation_blocked.py| 193 +++
tests/workflow/test_d_audit_704_activity_bridge_wired.py   | 317 ++++++++
10 files changed, 1919 insertions(+), 2 deletions(-)
```

**Only 1 source file was modified** (`mlflow_backend.py`, +14/-2), all other
changes are NEW test files. None of the files reported as fixed in
`{701..705}` appear in the diff (`tools/config_audit.py`,
`tools/codegen_settings.py`, `src/backend/dsl/engine/processors/scan_file.py`,
`src/backend/plugins/composition/setup_infra/lifecycle.py`,
`src/backend/services/ai/rag_query_stats.py`).

### 2. T-C7-01 (D-AUDIT-701) — `config_audit.py` + `codegen_settings.py` path fix: **NOT APPLIED**

Commit message claim:
> `src/backend/core/config/` (correct) vs stale `src/core/config/` (wrong)
> runtime: Discovered 69 settings classes (was 0 broken)

Actual state (read at runtime, 2026-08-07):

`tools/config_audit.py:36` (verbatim, unchanged):
```python
CONFIG_DIR = ROOT / "src" / "core" / "config"
```

`tools/codegen_settings.py:62-65` (verbatim, unchanged):
```python
SERVICES_DIR = ROOT / "src" / "core" / "config" / "services"
SETTINGS_FILE = ROOT / "src" / "core" / "config" / "settings.py"
SERVICES_INIT = SERVICES_DIR / "__init__.py"
INTEGRATION_BASE = ROOT / "src" / "core" / "config" / "integration_base.py"
```

Runtime (`.venv/bin/python tools/config_audit.py`, exit 1):
```
Discovered 0 settings classes in src/core/config; 56 keys in .env.example.
## profile: dev
  [ORPHAN-GROUP] vault, app, security, ... (38 issues)
```

Filesystem check (`ls src/core` → ENOENT, `ls src/backend/core/config` → exists
with 30+ files). The "69 settings classes" claim is **false**: 0 are discovered.

### 3. T-C7-03 (D-AUDIT-703) — `ScanFile` fail-OPEN → fail-CLOSED: **NOT APPLIED**

Commit message claim:
> `src/backend/dsl/engine/processors/scan_file.py:92-102` — removed fail-OPEN
> guard; on_threat=warn + backend unavailable → exchange.fail()

Actual `src/backend/dsl/engine/processors/scan_file.py:92-97` (verbatim, unchanged):
```python
except Exception as exc:
    _logger.warning("ScanFileProcessor: AV-бэкенд недоступен: %s", exc)
    exchange.set_property(f"{self._result_property}_error", str(exc))
    if self._on_threat == "fail":
        exchange.fail(f"ScanFileProcessor: AV-бэкенд недоступен: {exc}")
    return
```

`git blame -L 88,110`:
```
^f32638e1 (crazyivan1289 2026-06-14 10:24:52 +0300  88)             )
^f32638e1 (crazyivan1289 2026-06-14 10:24:52 +0300  92)         except Exception as exc:
^f32638e1 (crazyivan1289 2026-06-14 10:24:52 +0300  97)             return
```

The `if self._on_threat == "fail": exchange.fail(...)` guard is **STILL THERE**
and the lines are from `2026-06-14`, predating the cycle-7 commit by 54 days.
The fail-OPEN behavior persists: when `on_threat="warn"` and backend raises,
only a warning is logged and `return` is executed WITHOUT `exchange.fail()`.

The test the report claims to have renamed is unchanged:
`grep -rn "test_scan_file_backend_unavailable_warn_mode" tests/` →
`tests/unit/dsl/wave11/test_scan_file_processor.py:305:
async def test_scan_file_backend_unavailable_warn_mode_does_not_fail(`

The "fail-CLOSED" rename did not happen. This is a **security regression
left unfixed**.

### 4. T-C7-04 (D-AUDIT-704) — `ActivityBridge` wiring in production lifespan: **NOT APPLIED IN THIS COMMIT**

Commit message claim:
> `register_langgraph_checkpoint_activities` wired в production lifespan

Actual `git blame -L 230,250 src/backend/plugins/composition/setup_infra/lifecycle.py`:
```
c2a0759ca (Kimi Code 2026-08-07 14:05:39 +0300 234) """D-AUDIT-704 fix (cycle 7): wire ActivityBridge в production lifespan.
```

The D-AUDIT-704 marker (and the actual wiring code) is in commit
`c2a0759c` (Aug 7 14:05:39), **not** in `39af04a7` (Aug 7 14:08:16). The
lifecycle.py file is not in the file list of `39af04a7`. The claim is
retroactive.

### 5. T-C7-06 (D-AUDIT-706) — `rag_query_stats.py` dangling-reference cleanup: **NOT APPLIED IN THIS COMMIT**

`git blame src/backend/services/ai/rag_query_stats.py`:
```
0e194233e (Kimi Code 2026-08-07 12:21:39 +0300   1) """Сбор top-N RAG-запросов per-tenant для аналитики и observability.
e3d9c93be (Kimi Code 2026-08-07 14:02:43 +0300   5) D-A9-02 fix (cycle 1): prewarm-подсистема ...
e3d9c93be (Kimi Code 2026-08-07 14:02:43 +0300   9) ... cycle-7/D-AUDIT-706 — финальный cleanup
```

The "cycle-7/D-AUDIT-706" docstring marker was added in commit `e3d9c93b`
(Aug 7 14:02:43), **5 minutes before** `39af04a7` (Aug 7 14:08:16). The file
is not in the file list of `39af04a7`. The cleanup was already done.

### 6. T-C7-02 (D-AUDIT-702) — `WorkflowBuilder.then()` verification: **CORRECT (no source change needed)**

`.then()` exists at `src/backend/dsl/workflow/builder/__init__.py:93`. Git blame:
```
d2c37d097 (Kimi Code 2026-08-07 09:44:12 +0300  93)     def then(self, step: WorkflowStep) -> Self:
```
This was committed in cycle 1 (D-A8-06), not cycle 7. The report's "marker
only (no source change)" admission is accurate. This is the **only honest
item** in the 6-fix list.

### 7. T-C7-05 (D-AUDIT-705) — `test_text_rag_e2e.py` NEW: **APPLIED (legit)**

508-LOC new file `tests/e2e/test_text_rag_e2e.py` with 5 E2E tests. Uses
real `RAGService` + real `RecursiveChunker` + in-memory `BaseVectorStore` +
deterministic `StubEmbedder` + `StubLiteLLM`. Test-masking is consistent with
the established multimodal pattern (per `docs/rag/MULTIMODAL_TESTING.md`):
external ML/network boundaries are stubbed; core components under test are
real.

Runtime (`pytest tests/e2e/test_text_rag_e2e.py -v -m e2e`): **5 passed in 0.30s.**

---

## Verification checklist (8 points from parent brief)

| # | Requirement | Result | Evidence |
|---|---|---|---|
| (a) | No hidden TODO/FIXME/pass/NotImplemented introduced | **PASS** | `git diff 39af04a7~1 39af04a7 \| grep -E "^\+.*\b(TODO\|FIXME\|XXX\|HACK\|NotImplemented\|pass$)\b"` → 1 match: `pass` body of `class _MsgPickleHost` in `test_data_formats_msgpack_rce.py` (legitimate empty class body, not an anti-pattern). 0 TODO/FIXME/HACK in any new file. |
| (b) | Test-masking vs real runtime, esp. text-RAG E2E | **PASS** | E2E test uses real `RAGService` (no `monkeypatch.setattr` on it), real `RecursiveChunker`, in-memory `BaseVectorStore` (implements full `BaseVectorStore` contract). Stubs: `StubEmbedder` (token-overlap, 16-dim, fully deterministic) and `StubLiteLLM` (registered via `sys.modules` swap). External ML boundary only. 5/5 pass. |
| (c) | Fallback branches removed (config_audit, ScanFile) | **FAIL** | Both fallback paths still in place. `tools/config_audit.py:36` → `src/core/config/` (stale, dir does not exist) → "Discovered 0 settings classes" + 38-39 ORPHAN-GROUP issues. `scan_file.py:92-97` → `if self._on_threat == "fail": exchange.fail(...)` guard + bare `return` (fail-OPEN persists for `on_threat="warn"`). |
| (d) | Docstring markers `cycle-7/D-AUDIT-7XX` in Russian docstrings | **FAIL** | Markers are in `lifecycle.py:184/234/340` and `rag_query_stats.py:5/9`, but those files are NOT in commit `39af04a7` (markers are from prior commits `c2a0759c` and `e3d9c93b`). No marker was added in the files the commit claims to have touched. Test files have the markers, source files do not. |
| (e) | No new `except Exception: pass` introduced | **PASS** | `git diff 39af04a7~1 39af04a7 \| grep "^\+.*except\s+Exception"` → 2 matches, both are docstring/comment text describing what was REMOVED, not actual except clauses. The single real change in `mlflow_backend.py` NARROWS the existing bare `except Exception: pass` to `except (ConnectionError, TimeoutError, RuntimeError)` + debug log. Net effect: removes one anti-pattern. |
| (f) | Cycle 1+2+3+4+5+6 changes not rewritten | **PASS** | Working tree has 0 modifications to tracked files (`git status -uno` → empty). All cycle 1-6 work in HEAD is intact. The cycle-7 commit only ADDS 8 test files (mostly for cycle-6 P0 fixes that lacked tests in `4c0bd0de`) and modifies 1 source file. |
| (g) | Forbidden files untouched | **PASS** | `git diff 39af04a7~1 39af04a7 -- uv.lock src/backend/services/storage/s3.py deploy/blue_green.sh tests/unit/entrypoints/api/v1/endpoints/test_blue_green_switch.py .security/pip-audit-allowlist.txt` → all empty diffs. Allowlist count: 27 (matches claim, no new entries). |
| (h) | `gateway_adapter.py:128-129` not touched | **PASS** | File not in commit's file list. The pre-existing cycle-1/B-05 try/except for `get_ai_gateway_provider` is intact (verified by `sed -n '125,135p'`). |

---

## Additional findings (out of scope but worth noting)

### A. Cycle-7 commit is a "kitchen sink" of cycle-6 test debt

6 of 8 new test files in `39af04a7` are actually for **cycle-6** P0 fixes that
were committed in `4c0bd0de` without tests:

| New test file | References | Claimed by |
|---|---|---|
| `test_auth_selector_saml_fail_closed.py` | `cycle-6/D-AUDIT-601` | D-A1-04 (cycle 6) |
| `test_auth_required_saml_impersonation_blocked.py` | `cycle-6/D-AUDIT-601` | D-A1-04 (cycle 6) |
| `test_data_formats_msgpack_rce.py` | `cycle-6/D-AUDIT-603` | DOMAIN-P0-003 (cycle 6) |
| `agent_memory.py` | `cycle-6/D-AUDIT-606` | D-A1-09 (cycle 6) |
| `test_hitl.py` | `cycle-6/D-AUDIT-607` | D-A1-09 (cycle 6) |
| `test_admin_cron.py` | `cycle-6/D-AUDIT-608` | API-P0-002 (cycle 6) |
| `test_d_audit_704_activity_bridge_wired.py` | `cycle-7/D-AUDIT-704` | cycle 7 ✓ |
| `test_text_rag_e2e.py` | `cycle-7/D-AUDIT-705` | cycle 7 ✓ |

All 42 tests in the cycle-6 files PASS at runtime (verified). So the tests
themselves are good; the **framing** as "cycle-7 architectural fixes" is
misleading.

### B. Real source change in this commit is **D-A1-04 (cycle 30)** work, not cycle 7

`mlflow_backend.py:22` has the marker `D-A1-04 fix (cycle 30)`. The change
narrows `except Exception: pass` to `except (ConnectionError, TimeoutError,
RuntimeError)` with debug logging. This is real, applied, and good — but it
should have been in a cycle-30 commit, not cycle 7. The cycle-7 commit message
does not even mention this change.

---

## Summary of unresolved items

1. **CRITICAL — T-C7-01 fix not applied:** `tools/config_audit.py:36` and
   `tools/codegen_settings.py:62-65` still point to `src/core/config/`
   (non-existent path). `Discovered 0 settings classes` + 38-39 ORPHAN-GROUP
   issues per profile. The audit tool is broken; commit message claim of "69
   settings classes" is false.

2. **CRITICAL — T-C7-03 fix not applied (security regression):**
   `src/backend/dsl/engine/processors/scan_file.py:92-97` still has the
   `if self._on_threat == "fail":` guard around `exchange.fail()`. When
   `on_threat="warn"` and AV backend is unavailable, exchange continues
   without scan — fail-OPEN behavior for security tooling. The
   `test_scan_file_backend_unavailable_warn_mode_does_not_fail` test was
   not renamed to `..._fails_closed` as claimed.

3. **CRITICAL — Commit message over-claims:** T-C7-04 (ActivityBridge
   wiring) and T-C7-06 (RagCachePrewarmer cleanup) are attributed to
   `39af04a7` but the actual source changes are in prior commits
   `c2a0759c` and `e3d9c93b`. The cycle-7 commit is a "kitchen sink"
   that takes credit for work done earlier in the day.

4. **MEDIUM — Misattribution:** The real source modification in
   `39af04a7` (`mlflow_backend.py` D-A1-04 narrow exceptions) is cycle-30
   work, not cycle 7. The commit message is silent on this change.

5. **LOW — Test attribution drift:** 6 of 8 new test files are for
   cycle-6 P0 fixes; 2 are genuine cycle-7. Both groups PASS at runtime,
   so the tests are valid — but the commit's narrative is misleading.

---

## Evidence trail (commands run, with exit codes)

```
$ git show 39af04a7 --stat                           # exit 0
$ git show 39af04a7 --name-only --format=           # exit 0
$ git diff 39af04a7~1 39af04a7 -- src/               # exit 0; 14 lines in mlflow_backend.py only
$ git blame -L 88,110 src/backend/dsl/engine/processors/scan_file.py
  → ^f32638e1 (2026-06-14) for lines 88-97, including the fail-OPEN guard
$ git blame -L 230,250 src/backend/plugins/composition/setup_infra/lifecycle.py
  → c2a0759ca (2026-08-07 14:05:39) for D-AUDIT-704 markers
$ git blame src/backend/services/ai/rag_query_stats.py
  → e3d9c93be (2026-08-07 14:02:43) for D-AUDIT-706 marker
$ cat tools/config_audit.py | sed -n '36p'
  → CONFIG_DIR = ROOT / "src" / "core" / "config"   # stale path
$ cat tools/codegen_settings.py | sed -n '62,65p'
  → 4 stale paths to src/core/config/...
$ .venv/bin/python tools/config_audit.py
  → exit 1
  → "Discovered 0 settings classes in src/core/config; ..."
  → "[ORPHAN-GROUP] ..." × 38-39 per profile
$ ls src/core                                        # ENOENT
$ ls src/backend/core/config                         # 30+ files exist
$ grep -rn "test_scan_file_backend_unavailable_warn_mode" tests/
  → tests/unit/dsl/wave11/test_scan_file_processor.py:305:
    async def test_scan_file_backend_unavailable_warn_mode_does_not_fail(
  → No `_fails_closed` test exists
$ .venv/bin/python -m pytest tests/e2e/test_text_rag_e2e.py -v -m e2e
  → exit 0
  → 5 passed in 0.30s
$ .venv/bin/python -m pytest tests/workflow/test_d_audit_704_activity_bridge_wired.py -v
  → exit 0
  → 9 passed in 3.35s
$ .venv/bin/python -m pytest tests/unit/core/auth/test_auth_selector_saml_fail_closed.py \
  tests/unit/services/auth/test_auth_required_saml_impersonation_blocked.py \
  tests/unit/services/ai/agent_memory.py \
  tests/unit/entrypoints/api/v1/endpoints/test_hitl.py \
  tests/unit/entrypoints/api/v1/endpoints/test_admin_cron.py -v
  → exit 0
  → 42 passed, 2 warnings
$ .venv/bin/python -m pytest tests/unit/dsl/wave11/test_scan_file_processor.py
  → exit 0
  → 23 passed in 1.85s (all 23 OLD tests pass; new fail-CLOSED test absent)
$ .venv/bin/python -m tools.check_docstrings --summary
  → exit 0
  → "Total: 0 missing docstrings in 0 files. Files scanned: 2278"
$ make check-docstrings MAX_ALLOWED=0
  → exit 0
  → "docstring policy OK" (840 files)
$ grep -cE "^CVE-|^GHSA-|^PYSEC-" .security/pip-audit-allowlist.txt
  → 27 (matches claim, no new entries)
$ git diff 39af04a7~1 39af04a7 -- uv.lock src/backend/services/storage/s3.py \
  deploy/blue_green.sh tests/unit/entrypoints/api/v1/endpoints/test_blue_green_switch.py \
  .security/pip-audit-allowlist.txt
  → empty (all forbidden files untouched)
$ git status -uno --porcelain
  → empty (no tracked file modifications outside commit)
```

---

## Recommendations

1. **REJECT commit 39af04a7** — the commit message is materially false. The
   PR author must either (a) amend the message to accurately describe the
   actual scope (one D-A1-04 narrow-exception fix + 8 test files for cycle-6
   and cycle-7 work), or (b) reopen the missing work as separate commits.

2. **Re-open the 3 unresolved source fixes as new tasks:**
   - T-C7-01 (config_audit path) — 2 file edits, ~8 lines
   - T-C7-03 (ScanFile fail-CLOSED) — 1 file edit, ~7 lines + 1 test rename
   - Plus verify D-AUDIT-704 wiring is still in place after the commit
     (lifecycle.py is unchanged in this commit, so should be OK from
     `c2a0759c`).

3. **Do not accept developer reports on trust** — the audit reports
   `cycle-7-D-AUDIT-{701..706}-report.md` describe intended work, not
   actually-applied work. Cross-check every claim against `git show --stat`
   and runtime verification before approval.

4. **Re-run the cycle-7 phase-5 review only after** items 1-3 are addressed
   in new atomic commits with their own audit reports and a clean
   `git show --stat`.

---

**End of critic report.**
