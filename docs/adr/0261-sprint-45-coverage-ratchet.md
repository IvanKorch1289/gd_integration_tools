# ADR-0259: Sprint 45 coverage ratchet — 2-3pp/cycle honest climb to 60%

> **Status**: PROPOSED (cycle 249, Sprint 45 planning)
> **Cycle**: 249
> **Method**: ratchet, not leap. 3 work-streams × 2-3pp each = realistic +5-7pp
> Sprint 45 lift from 1% → 3-4% baseline.
> **Out of scope**: lowering `fail_under=60` (separate ADR if ever raised).

## 0. TL;DR

| Metric | Value | Source |
|---|---|---|
| **Real coverage (cycle 247, S44 W32)** | **1%** (23554 / 107349 stmts) | `docs/STATUS.md` §S44 W32 |
| `fail_under` gate | 60% | `pyproject.toml:1080` |
| **Gap to gate** | **59 percentage points** | 60 - 1 |
| W29 misleading claim | "12% on `core/ai/` + `agent_security`" narrow subset | commit `554f4ce0` (honest retraction) |
| W32 honest re-measurement | **1% on full pytest subset** (4744 passed / 34 failed / 50 skipped) | commit `554f4ce0` + `docs/STATUS.md` |
| Realistic Sprint 45 target | **+2-3pp** (1% → 3-4%) | this ADR |
| Sprints to reach 60% (naive, optimistic) | ~20 sprints (~10 months) at constant 3pp/cycle | this ADR §3 |
| Sprints to reach 60% (realistic w/ diminishing marginal return) | **3-4 sprints for +5pp** then plateau | §3.2 |

**Ratchet, not leap.** Coverage is the LAST gate to relax — there is no shortcut
without lying about numbers. The W29 "12%" claim is the cautionary tale:
documented honestly in `554f4ce0`, retracted, re-measured at 1% in S44 W32.

## 1. Context

### 1.1 Real coverage measurement (cycle 247, S44 W32)

Re-measured on BROADER subset than W29:
- **Method**: `pytest --cov=gd_integration_tools tests/unit/core/ai/ tests/unit/services/agent_security/ tests/unit/dsl/`
- **Result**: TOTAL 1% (23554 covered / 107349 statements)
- **fail_under=60%**: FAIL by 59pp

Source: `docs/STATUS.md` §S44 W32 — coverage FULL re-measurement (cycle 247).

### 1.2 Why the W29 "12%" was misleading

The Sprint 44 W29 measurement reported "12% coverage" but only exercised a
**narrow subset** of the project (`core/ai/` + `agent_security/` test paths).
The honest re-measurement at W32 on a broader subset returned **1%**.

This was **documented honestly in commit `554f4ce0`** (Sprint 44 W32) and
recorded as a retrospective lesson in ADR-0257 §6.3 Lesson 2:
*"Bounded subset gives lower coverage than full run. A subset of 4 test files
testing ~2% of project will get ~2-15% coverage — accurate for THAT subset.
Don't claim 'project coverage = 13%'."*

**Lesson applied to this ADR**: we quote **full-project measurements only**,
with the exact subset and command documented alongside. No "X% on subset"
presented as project coverage.

### 1.3 Project scale

- **2308 Python files** in `src/` (verified 2026-08-25)
- **~1586 test files** in `tests/`
- **107349 statements** measured by `coverage` (107360 in latest run, ±11
  statements depending on which subset was last loaded)
- **`fail_under=60`** gate is enforced by `pyproject.toml:1080` — exists
  since pre-Sprint 44, was effectively vacuous until S44 W4 (ADR-0257).

### 1.4 Why ratchet, not leap

A "leap" approach (target +20pp in one sprint) would require:
- Writing ~3000-5000 new tests across uncovered services
- Each test requires domain knowledge + setup fixtures
- ~3-5 days of pure test-writing with zero feature work
- High risk of flaky tests covering false paths

A **ratchet** approach (2-3pp per cycle, sustainable pace):
- Small focused diffs per cycle (one stream at a time)
- Tests land with the code they exercise (no orphan tests)
- Honest measurement at each W-commit
- Feature work continues in parallel

**Ponytail alignment**: the principle "shortest working diff wins" applies —
each stream produces ~+1pp with ~50-200 LOC of test code. No speculative
scaffolding for "future coverage we might want".

## 2. Decision

Sprint 45 lifts coverage by **+2-3pp via 3 parallel work-streams**. Each
stream is independently shippable. We measure incrementally per-W and
re-publish the gate delta in `docs/STATUS.md` at W28/W32/W36/W40.

### Stream A: Top 10 uncovered modules by statement count

**Goal**: +1pp project coverage via 10 focused unit-test files
on the largest zero-coverage modules.

**Source list** (top 10 by `coverage report` stmts, all currently 0%):

| # | Module | Stmts | Why low | Test strategy |
|---|---|---:|---|---|
| 1 | `src/backend/dsl/builders/base/__init__.py` | 321 | DSL builder base — pure logic | unit-test all builder primitives |
| 2 | `src/backend/infrastructure/clients/storage/s3_pool/client.py` | 273 | S3 client — needs moto fixture | moto-based smoke + retry path tests |
| 3 | `src/backend/core/dsl/variables.py` | 250 | DSL variable substitution | property-based (Stream C also touches this) |
| 4 | `src/backend/dsl/engine/processors/scraping.py` | 245 | RPA scraping — needs HTML fixtures | snapshot tests against canned HTML |
| 5 | `src/backend/dsl/engine/processors/rpa_browser.py` | 242 | RPA browser — needs playwright | already covered partially in E2E; lift via unit |
| 6 | `src/backend/dsl/engine/processors/eip/transformation.py` | 237 | EIP transform processor | table-driven unit tests |
| 7 | `src/backend/infrastructure/storage/s3.py` | 228 | S3 facade | moto + retry decorator test |
| 8 | `src/backend/entrypoints/email/imap_monitor.py` | 214 | IMAP monitor | mock imaplib, assert poll/parse |
| 9 | `src/backend/infrastructure/workflow/runner.py` | 213 | Workflow runner | LiteTemporalBackend-driven unit tests |
| 10 | `src/backend/core/auth/jwt_backend.py` | 212 | JWT backend | already tested (W7 lift); verify |

Combined: **2435 statements** ≈ 2.3% of 107349. Even 50% coverage on these
modules = ~+1.1pp project coverage. 100% coverage on top 5 alone ≈ +1.3pp.

**Constraint**: each module gets 1 test file, max 200 LOC. If a module
needs >200 LOC of tests, split or defer (don't bloat test files).

### Stream B: 17 entrypoint protocol smoke tests

**Goal**: +0.5pp project coverage + regression guard for each protocol.

**Background**: project advertises 14+ multi-protocol entrypoints (REST, SOAP,
WSDL, gRPC, GraphQL, AsyncAPI, WS, SSE, MCP, MQTT, HTTP3, CDC, email,
filewatcher, scheduler + a few experimental). Most have 0 coverage because
they're either integration-only or have no test fixtures.

**Action**: add 1 smoke test per protocol entrypoint. Each test:
- Imports the entrypoint module
- Calls `register()` or equivalent bootstrap
- Verifies the protocol object is created with expected attributes
- Doesn't require live server / network / docker

**Expected modules** (verify exact list during Sprint 45 W28 planning):
```
src/backend/entrypoints/api/__init__.py             (REST)
src/backend/entrypoints/soap/__init__.py            (SOAP)
src/backend/entrypoints/grpc/__init__.py            (gRPC)
src/backend/entrypoints/graphql/__init__.py         (GraphQL)
src/backend/entrypoints/websocket/__init__.py       (WS)
src/backend/entrypoints/sse/__init__.py             (SSE)
src/backend/entrypoints/mcp/__init__.py             (MCP)
src/backend/entrypoints/mqtt/__init__.py            (MQTT)
src/backend/entrypoints/http3/__init__.py           (HTTP3)
src/backend/entrypoints/cdc/__init__.py             (CDC)
src/backend/entrypoints/email/__init__.py           (email)
src/backend/entrypoints/filewatcher/__init__.py    (filewatcher)
src/backend/entrypoints/scheduler/__init__.py       (scheduler)
src/backend/entrypoints/asyncapi/__init__.py        (AsyncAPI)
src/backend/entrypoints/express/__init__.py         (Express)
src/backend/entrypoints/webhook/__init__.py         (webhook)
src/backend/entrypoints/stream/__init__.py          (Stream)
```

17 tests × ~10 LOC each = ~170 LOC of test code. Coverage impact:
modules are mostly `__init__.py` re-exports so +0.2-0.3pp each, total ~+0.5pp.

### Stream C: Property-based tests with `hypothesis`

**Goal**: +0.5pp + better regression detection on hot paths.

`hypothesis>=6.0.0` is **already in dev dependencies** (`pyproject.toml:582`).
No new dependency added (per ADR-0256 §1.3 + Sprint 35 W4 dep-conflict
history).

**Target modules** (3 picks, prioritized by hot-path + param surface):
1. `src/backend/core/dsl/variables.py` — variable substitution
   (pure function, easy Hypothesis strategies)
2. `src/backend/dsl/builders/base/__init__.py` — builder fluent API
   (state-machine strategies)
3. `src/backend/core/auth/jwt_backend.py` — token encode/decode
   (round-trip property + adversarial strategies)

**Per module**: 1 test file, 50-100 LOC. Property-based tests count as
multiple statements covered per test run — high coverage leverage per LOC.

**Constraint**: each property must include `@example` cases for known
boundary conditions (empty string, None, max length).

### Combined Sprint 45 delta

| Stream | LOC | Coverage gain |
|---|---:|---:|
| A: Top 10 modules | ~2000 (10 files × 200) | **+1.0pp** |
| B: 17 entrypoint smoke | ~170 | **+0.5pp** |
| C: Hypothesis ×3 | ~250 | **+0.5pp** |
| **Total** | **~2420 LOC** | **+2.0pp (target), +3.0pp (stretch)** |

**Sprint 45 target**: 1% → **3-4%**. Realistic, not optimistic.

## 3. Consequences

### 3.1 Realistic timeline to 60%

If we hold +2-3pp/cycle (assuming no module becomes saturated):
```
Sprint 45 (W28-W40):  1% → 3%   (+2pp)
Sprint 46:            3% → 5%   (+2pp)  — diminishing return kicks in
Sprint 47:            5% → 7%   (+2pp)  — top 30 modules now partially covered
Sprint 48:            7% → 9%   (+2pp)
Sprint 49:            9% → 11%
Sprint 50:            11% → 13%
...
Sprint 65 (S50-ish):  ~50-55%    — by now most modules have ≥1 test
Sprint 70 (S55-ish):  ~60%       — gate pass
```

**Naive extrapolation**: ~25 sprints (~12 months) at constant +2pp/cycle.

### 3.2 Realistic timeline with diminishing marginal return

Past ~10pp coverage, top modules are partially covered. Next +2pp requires
testing more modules but each contributes less:
- After ~30pp: marginal contribution drops to +0.5pp per 200 LOC of tests
- After ~50pp: marginal contribution drops to +0.2pp per 200 LOC of tests
- Reaching 60% requires substantial investment in services that are NOT
  exercised by unit tests (e.g., workflow Temporal integration, real DB
  drivers, real MQ brokers)

**Realistic estimate**: **3-4 sprints to reach 5-8%** (Stream A/B/C phase).
Then **+1pp/sprint** until ~20%. Then **+0.5pp/sprint** until ~50%.
Then **integration-test heavy phase** (services that need real backends) —
this is the hardest 10pp to gain.

**Total realistic timeline to 60%**: **12-20 sprints** (6-10 months)
assuming continued ratchet effort.

### 3.3 Risk: slowing feature work

**Concern**: dedicating ~2400 LOC per sprint to test code reduces feature
delivery capacity by ~10-15%.

**Mitigation**:
- Stream A tests live alongside the modules they cover → test code review
  surfaces bugs (free QA)
- Stream B tests catch protocol regressions early → reduces incident cost
- Stream C property tests catch edge cases humans miss → fewer prod bugs
- Net: ~5-10% feature velocity reduction, but ~30-50% reduction in
  regression incidents (estimated based on S44 W4-W9 retro data showing
  coverage-lift cycles had zero prod regressions)

### 3.4 Risk: false coverage

**Concern**: writing tests that execute code without verifying behavior
("coverage theater").

**Mitigation** (per ADR-0257 §6.3 Lesson 1):
- Each new test must have at least 1 assertion on observable behavior
- Tests that "just import and call" without assertion = reject in review
- `coverage report --fail-under=60` is enforced at CI; we don't gate on
  "covered" alone, we gate on "covered AND test passed"

### 3.5 Risk: aio-pika / otel pre-release pin re-emerges

**Concern**: full pytest with coverage may run into the aio-pika conflict
documented in ADR-0258.

**Mitigation**: if the conflict re-emerges, run coverage on `--ignore=tests/integration/ai --ignore=tests/integration/workflow` and document the narrower subset honestly (per §1.2 lesson).

## 4. Verification slice

### 4.1 Per-W commit measurement

Each W-commit (W28, W32, W36, W40) re-runs:
```bash
coverage run --source=src/backend -m pytest \
  tests/unit/core/ai/ \
  tests/unit/services/agent_security/ \
  tests/unit/dsl/ \
  tests/unit/services/ \
  tests/unit/infrastructure/ \
  -q --no-header
coverage report 2>&1 | tail -3
```

Result is **appended to `docs/STATUS.md`** under a new section:
```
## S45 W<N> — coverage ratchet progress
- Method: pytest <subset> --cov=gd_integration_tools
- Result: TOTAL <N>% (<covered> / <total> stmts)
- Δ from S44 W32 (1%): <signed delta>pp
- Stream A/B/C breakdown: <per-stream contribution>
```

### 4.2 Per-cycle gate check

End of cycle 250 (S45 W36 target):
```bash
coverage report --fail-under=60
```
Output MUST include `Coverage failure: total of <N> is less than fail-under=60`
(we still expect failure until ~Sprint 65+; this is informational, not blocking).

### 4.3 CI integration

The `coverage report --fail-under=60` call is **NOT added to CI** in Sprint 45
(because we know it will fail). Instead, a **soft warning** is added:
```yaml
- name: Coverage ratchet check (non-blocking)
  run: |
    coverage report 2>&1 | tail -3
    echo "::warning::Coverage is <N>% (target Sprint 70: 60%)"
  continue-on-error: true
```

**Hard gate** is added in a separate ADR when we believe we'll cross 60%
within 2 sprints (currently estimated Sprint 65+). Not before.

### 4.4 Honest accounting

The cardinal rule: **never claim project coverage without the full subset
and exact command**. Every `docs/STATUS.md` entry must include both.

## 5. Non-goals (explicit)

This ADR does NOT:
- Lower `fail_under=60` (separate ADR if ever proposed — would need explicit
  user approval and would mark the project as knowingly below production
  readiness)
- Add coverage tools as new deps (hypothesis already in dev deps; coverage
  already in dev deps)
- Disable coverage measurement or skip `--cov` flags
- Promise a specific sprint-by-sprint number (only ranges: +2-3pp Sprint 45)
- Touch `fail_under` gate value

## 6. References

- `docs/STATUS.md` §S44 W32 — coverage FULL re-measurement (cycle 247)
  — the 1% baseline
- `docs/STATUS.md` §S44 W4 — coverage extension, real measurement 13% (later
  retracted to 1% as subset widened)
- `docs/adr/0257-coverage-extension-real-measurement-13pct.md` — W4 honest
  re-measurement + retrospective lessons
- commit `554f4ce0` — Sprint 44 W32 honest gap documentation
- `pyproject.toml:1080` — `fail_under = 60`
- `pyproject.toml:582` — `hypothesis>=6.0.0` (dev dep, already present)
- `pyproject.toml:1048` — `property: hypothesis property-based tests` marker
- ADR-0258 (aio-pika dependabot blocker) — for full-pytest avoidance strategy
- ADR-0256 (otel pin) — `aio-pika` pre-release constraint context
- ADR-0255 (L5 Security Chain) — example of how focused testing lifted a
  specific module to 100% (S44 W6/W7/W8)

## 7. Decision log

| Date | Cycle | Action |
|---|---|---|
| 2026-08-25 | 249 | ADR PROPOSED — Sprint 45 plan + 2-3pp target |
| TBD | 250+ | Sprint 45 W28: Streams A+B+C started |
| TBD | 250+ | Sprint 45 W32: first measurement check |
| TBD | 250+ | Sprint 45 W36: midpoint review |
| TBD | 250+ | Sprint 45 W40: final Sprint 45 measurement + retrospective |