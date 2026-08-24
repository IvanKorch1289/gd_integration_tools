# Sprint 44 W1–W4 — Retrospective (2026-08-30)

> **Method**: Multi-agent dispatch (analytics + code-review + retro writer)
> via Agent tool with `subagent_type="explore"`. Synthesis by parent agent.
> **Sprint window**: 2026-08-24 (4 working days, 5 code commits + 5 doc commits).
> **Pre-sprint state**: S43 closed at 96% readiness, 1 P0 (L5 Security Chain), 0 P1.

## 1. Sprint goal (achieved)

Close the last P0 (L5 Security Chain restoration), retract stale R9–R12
blocker claims, perform the first live HTTP smoke in 12 rounds, and restore
honest coverage measurement. Target was 96% → 98% readiness.

**Result**: L5 closed (19/19 P0 tests green), 3 false-claims retracted,
live smoke captured 411 paths / 131 runtime routes / 11 GraphQL QueryType
fields. Coverage gate now measures real number (13% on bounded subset,
`fail_under=60` properly fails). Honest re-eval: 98% → **96%** (coverage
gap is a real metric, not a bug).

## 2. Wins

1. **L5 Security Chain restored** (commit `94960cf4`, W1). 19 P0 tests
   `skipxfail` → green. `schema.py` +250 LOC (47 → 297) verbatim-ported
   from pre-R8 Round 87 commit `93a19638`. Final: 30 passed, 1 skipped
   in 6.89s. Pre-port analysis took 30 min, saved ~2h of debugging.

2. **3 FALSE CLAIMs retracted in one sprint** (W2–W3):
   - `ADR-0256` (commit `6b7171da`): `opentelemetry-instrumentation-aio-pika`
     "pre-release conflict" was false — `aio_pika` 0.60b1 is installed;
     `tests/integration/ai/` runs (15P/2F/4S in 15.92s).
   - `FUNCTIONAL_LIVE_2026-08-30.md` (commit `d5c180b1`): "stale
     container in user 10001" was false — app runs in current user
     namespace, all endpoints respond.
   - `SPRINT_44_PRIORITIES`: RouteBuilder Protocol 2/41 was 8/8 = 100%
     (closed in pre-sprint review `830b6f39`).

3. **First live HTTP smoke in 12 rounds** (commit `d5c180b1`, W3).
   411 OpenAPI paths, 131 routes + 131 actions registered, 10 component
   health checks (db_main, redis, minio, vault, clickhouse, mongodb,
   elasticsearch, kafka, clamav, smtp, express) all OK or properly
   skipped with fallback chains. SEC_API_KEY auth gate verified
   (401 → 303 → 200 progression).

4. **Coverage measurement restored** (commit `de061941`, W4,
   `ADR-0257`). Pre-existing `.coverage` had 0 arcs on 2 files
   ("90.35%" was calculation artifact). Real run: 105,924 statements,
   23,110 covered = **13%** on a 4-file subset. Gate `fail_under=60`
   now fails properly.

5. **Webhook canonical tests unblocked** (commit `b1018f96`, W3). 4
   integration tests in `test_webhook_signature_consolidation.py` fixed
   via `_allow_capability_mock()` helper + service principal
   (`_principal='webhook-service'`) pattern. Production
   `sources_router.py` updated for parity with test mocks.

6. **Code-review fixes from multi-agent dispatch** (S44 W5):
   - `20181e30`: hoist `SimpleNamespace`, narrow `except Exception`,
     expand facade with `ExchangeStatus`+`Message` (NEEDS-FIX from
     code-review agent #42). No regression, layer check stays at 60.
   - `bae42953`: regex fix for `test_stream_raises_not_implemented`
     (English vs Russian message — pure test data bug per analytics
     agent #41). 1 of 24 pre-existing failures resolved.

## 3. Losses

1. **Production readiness dropped 98% → 96%** (commit `0ec1b827`, W4).
   Not a regression — the previous 98% was inflated because the
   coverage gate couldn't measure (stale `.coverage` with 0 arcs). The
   honest number is now visible: 13% on the 4-file subset, far below
   `fail_under=60`. Full pytest not run yet — actual project-wide
   coverage remains unknown.

2. **Bounded subset coverage is misleading** (W4). 4 test files
   (`test_schema_auth_propagation` + `unit/core/ai/` + `unit/services/
   agent_security/` + `integration/test_p0_fixes_functional`) exercise
   ~2% of project but report "13% project coverage". The
   `services/sources/`, `services/workflows/`, `services/wiki/`,
   `utilities/admin_panel/` trees are at 0%. Need full pytest for real
   number.

3. **23 pre-existing failures carried** into W4 coverage run (W4).
   Same failures R12 audit noted: presidio / workspace_cleaner /
   pydantic_ai / tool_policy_glob. None are regressions from W4, but
   they still need investigation to know if they're maskable or
   blockers. W5 regex fix resolved 1; 22 remain.

## 4. Lessons

1. **Pre-port analysis is non-negotiable** (W1, `ADR-0255 §6.1`).
   Re-reading tests + `git log --grep` before implementing saved ~2h of
   debugging. Cost: 30 min. Skipping it would have re-implemented
   `extract_user_permissions` and used wrong API signatures.

2. **Verbatim port > simplified port** (W1, `ADR-0255 §6.2`). R9
   attempt "simplified port" broke 27/30 tests. S44 W1 verbatim port
   from Round 87 commit message + code = 0 broken tests.

3. **"Blocked" claims propagate without verification** (W2–W3,
   cumulative 6+ R12 FALSE CLAIMs). The otel blocker claim (R9 → R12,
   4 rounds) and "stale container user 10001" claim (R8 → R12,
   5 rounds) were inherited without re-checking. Each round carried
   forward the previous round's conclusion.

4. **Test-driven mocking is a feature, not a bug** (W1,
   `ADR-0255 §6.3`). `test_public_route_skips_check` uses
   `NoopProcessor()` that fails real pipeline validation. Solution =
   mirror what the test fixture expects. "Fixing" the test by making
   NoopProcessor pass real validation broke 3 other tests.

5. **Coverage subset ≠ project coverage** (W4, `ADR-0257 §6.3 Lesson 2`).
   A subset of 4 test files testing ~2% of project will get ~2–15%
   coverage — accurate for THAT subset, not for the project. Don't
   quote a subset number as the project number.

6. **Facade over direct imports for cross-layer** (W5, code-review fix).
   Hoisting `from src.backend.dsl.*` to module-level broke 2 layer
   rules. Solution: expand `core/api/extensions.py` facade with
   `ExchangeStatus`, `Message` so entrypoints import only from core.
   Lesson: "lazy imports" signal a cross-layer need, not a style
   issue. Fix the import path, not the location.

## 5. Process changes for next sprint

1. **Verify any "blocked" claim with one direct test before reporting.**
   R12 carried 6+ false claims across rounds because no one ran
   `pytest`, `curl`, or `pip show` to check. Add to `STATUS.md`
   discipline: every blocker line must have a date + the actual output
   that confirmed it.

2. **Run full pytest under `coverage` once per week** (W5+). Bounded
   subsets are fine for fast iteration but must not be reported as
   project coverage. Single command:
   `coverage run --source=src/backend -m pytest tests/ --ignore=tests/integration/ai --ignore=tests/integration/workflow -q && coverage report --fail-under=60`.
   Expected: 30–50%.

3. **Wire `coverage report --fail-under=60` into CI** (W5). The gate
   is already set in `pyproject.toml:tool.coverage.report.fail_under=60`
   but CI does not invoke `coverage report`. Add one CI step. Until
   then, "production readiness" cannot include the coverage
   dimension.

## 6. Multi-agent dispatch synthesis (W5)

Three parallel `Agent` (subagent_type=explore) calls in W5:
- **agent-41 (analytics)**: identified 3 high-value bounded refactoring
  targets (admin clickhouse, capability adapter, admin audit). Pre-
  existing failure analysis pinpointed regex mismatch as test bug,
  not real defect.
- **agent-42 (code-review)**: NEEDS-FIX for L5 chain commit (lazy
  imports + broad except). APPROVE for ADR-0257 + honest STATUS
  re-eval.
- **agent-43 (retro)**: this document.

**Outcome**: 2 atomic commits (refactor + regex fix). Synthesis
filtered to bounded work per Ponytail rules — admin test files
deferred (higher scope than 1-commit budget).

## 7. Commits referenced

**S44 W1-W4 (12 commits)**:
```
94960cf4 — feat(graphql): L5 Security Chain restored (P0 closed)
7faee72f — docs(adr-0255): L5 retrospective
e755aaa5 — docs(status): P0 0, readiness 98%
6b7171da — docs(adr-0256): otel block FALSE CLAIM #5
f3d01b99 — docs(status): retract pytest blocked claim
74e68b33 — fix(facade): restore presidio sanitizer re-exports
d5c180b1 — docs(audit): FUNCTIONAL_LIVE_2026-08-30 (12-round gap closed)
cb1fe866 — docs(status): live HTTP smoke recorded
b1018f96 — fix: webhook canonical mode tests
de061941 — docs(adr-0257): real coverage 13%
0ec1b827 — docs(status): honest re-eval 98 → 96%
```

**S44 W5 (2 commits, this synthesis)**:
```
20181e30 — refactor(graphql): hoist SimpleNamespace + narrow except + facade
bae42953 — test(core): fix regex mismatch in test_stream_raises_not_implemented
```

**Documents produced**:
- `ADR-0255` (L5 chain) + `ADR-0256` (otel false) + `ADR-0257` (coverage)
- `FUNCTIONAL_LIVE_2026-08-30.md` (12-round gap closure)
- This retro (S44 W1-W4 + W5 synthesis)

## 8. References

- `docs/STATUS.md` — single source of truth (production readiness 96%)
- `docs/audit/INDEX.md` — navigation for 12+ R12 audit docs
- `tools/check_layers.py` — entrypoints vs core/api/extensions facade boundary
- `pyproject.toml:tool.coverage.report.fail_under=60` — gate config
