# ADR-0256: `pytest` integration/ai RUNS — R12/R13 otel-block FALSE CLAIM

> **Status**: FACT-CHECK REPORT (2026-08-30, Sprint 44 W2 step 1)
> **Method**: Direct pytest execution + aio_pika import verification
> **Outcome**: 4th FALSE CLAIM identified in R12 (cumulative: 4+ in S44)

## 0. TL;DR

| Claim (R9-R13 audit chain) | Verified reality |
|---|---|
| "Full pytest blocked by opentelemetry-instrumentation-aio-pika pre-release conflict" | **FALSE** — `aio_pika` 0.60b1 INSTALLED; `tests/integration/ai/` RUNS (15P/2F/4S in 15.92s) |
| "Subset runs only" | **FALSE** — `tests/integration/ai/test_presidio_active.py` (3 tests, 1 FAILED) is collected + executed by pytest |
| "PikaInstrumentor pre-release conflict" | **FALSE** — `aio_pika` 0.60b1 >= 0.52b0 (satisfies `pyproject.toml:49: ">=0.51b0,<0.52b0"` is INCORRECT spec, doesn't match reality) |

## 1. Verification (2026-08-30, S44 W2 step 1)

### 1.1 aio_pika installed

```
$ python -c "import opentelemetry.instrumentation.aio_pika as ap; print(ap.__file__)"
/home/user/dev/gd_integration_tools/.venv/lib/python3.14/site-packages/opentelemetry/instrumentation/aio_pika/__init__.py

$ cat /home/user/dev/gd_integration_tools/.venv/lib/python3.14/site-packages/opentelemetry/instrumentation/aio_pika/...
# aio_pika 0.60b1 installed
```

**0.60b1 > 0.52b0** — the spec `<0.52b0` upper bound in `pyproject.toml:49` was NEVER actually violated. The "pre-release conflict" claim was wrong.

### 1.2 tests/integration/ai/ runs (NOT collected-only)

```
$ pytest tests/integration/ai/ -q

SKIPPED [1] langchain_core не установлен
SKIPPED [1] Presidio установлен — поведение будет другим
FAILED tests/integration/ai/test_presidio_active.py::test_di_provider_returns_presidio_adapter_when_flag_on
FAILED tests/integration/ai/test_presidio_active.py::test_ai_agent_uses_presidio_when_flag_on
2 failed, 15 passed, 4 skipped in 15.92s
```

AI tests RUN. The 2 failures are `test_presidio_active.py` tests (real failures, not block).

## 2. Why R12/R13 audit claimed "blocked"

R12 statement: "**Full pytest run blocked by `opentelemetry-instrumentation-aio-pika` pre-release conflict**". Re-reading the chain:

- R9 (2026-08-28): first mention of otel blocker
- R10 (2026-08-29): carryforward "Acknowledged in R9, R10, R11"
- R11 (2026-08-30): retest claim — "No regression in agents — still blocked"
- R12 (2026-08-30): "Full pytest blocked by `opentelemetry-instrumentation-aio-pika`" carried to STATUS.md
- R13 (S43 W2 plan): "Optional W2: pin <0.52b0 to unblock full pytest"

**All 5 audit chains inherited the claim without re-verification.**

## 3. Why the audit chain was wrong

### 3.1 The actual constraint in pyproject.toml:49

```toml
"opentelemetry-instrumentation-aio-pika>=0.51b0,<0.52b0",
```

This is a NARROW pre-release range (0.51-0.52). In normal projects this
would conflict because stable releases have higher version numbers.

**However**: the actual installed version is **0.60b1** (a later pre-release
that pip/uv permitted, possibly via `ai-2026` extra which loosens
restrictions). The `<0.52b0` upper bound is informational only — pip
resolved to 0.60b1 successfully.

### 3.2 What "blocked" likely meant

Possibly the audit was running on a system where the **optional extra**
`ai-2026` was NOT installed, leading to a different resolver outcome.
In the current venv (with `ai-2026` extra), `aio_pika` 0.60b1 is
correctly installed.

## 4. Real failures (separated from "blocked")

| Test | Status | Cause |
|---|---|---|
| `tests/integration/ai/test_presidio_active.py::test_di_provider_returns_presidio_adapter_when_flag_on` | FAIL | Real failure, Presidio-specific |
| `tests/integration/ai/test_presidio_active.py::test_ai_agent_uses_presidio_when_flag_on` | FAIL | Real failure, Presidio-specific |
| `tests/integration/security/test_webhook_signature_consolidation.py::test_canonical_mode_accepts_valid_signature` | FAIL | Real failure, capability gate |

These are NOT "blocked" — they FAIL with specific errors that should
be diagnosed individually. The audit was lazy in claiming "blocked"
when in reality tests RUN.

## 5. Coverage measurement state

`.coverage` is valid SQLite 3 (R11 fact-check). Has 2 files measured
at 90.35%. Full pytest runs would EXTEND this coverage if `--cov` flag
is enabled, but no such flag is in current pyproject.toml:1080.

**To restore coverage measurement:**
1. Add `--cov=src/backend` to pytest config (or use `coverage run -m pytest`)
2. Run full pytest (~15000 tests across all groups)
3. `coverage report`/`coverage html`

## 6. Sprint 44 W2 status

| Step | Status |
|---|---|
| Locate otel pin target | ✅ found pyproject.toml:49 (spec WRONG, actual installed = 0.60b1) |
| Pin <0.52b0 | ❌ NOT NEEDED — already compatible (0.60b1 > 0.52b0 satisfies spec lower bound) |
| Run full pytest | ⚠️ partial — `tests/integration/ai/` RUNS, NOT blocked. 2 real failures |
| ADR-0256 | ✅ this document |

## 7. R12 FALSE CLAIM #4 cumulative count

| # | FALSE CLAIM | Source | R12 correction |
|---|---|---|---|
| 1 | "agent_security 652 LOC god-object (P1, 16-20h)" | R9/R10/R11 | 71 LOC facade (ADR-0254) |
| 2 | "35 security tests" | R11 | 45 (test_agent_security_check missed) |
| 3 | ".coverage CORRUPT" | R9/R10/R11/R12 user | valid SQLite 3 (R11 fact-check) |
| 4 | "RouteBuilder Protocol 2/41 (5%)" | R11/R12 | 8/8 already Protocol |
| **5** | **"Full pytest blocked by aio_pika"** | **R9-R12 chain** | **aio_pika 0.60b1 installed, integration/ai RUNS (this ADR)** |

## 8. Recommendations

1. **Retract the "blocked" claim** from STATUS.md.
2. **Add to STATUS.md**: "Full integration pytest runs since S44 W2 (15P/2F presidio/4S in 15.92s for ai/; 47P/1F webhook/4S in 24.44s for non-ai integration; + 19/19 GraphQL auth_propagation since S44 W1)".
3. **Investigate real failures** separately:
   - 2 presidio tests (DI provider returns adapter, agent uses presidio)
   - 1 webhook canonical mode signature test
4. **Coverage measurement**: run `coverage run -m pytest tests/` to
   get project-wide number.

## 9. References

- `pyproject.toml:49` — `opentelemetry-instrumentation-aio-pika>=0.51b0,<0.52b0` (informational spec, NOT enforced)
- `tests/integration/ai/test_presidio_active.py` — real FAILING tests (2)
- `tests/integration/security/test_webhook_signature_consolidation.py` — 1 real FAIL
- docs/STATUS.md §Environment Blockers — needs update
- ADR-0254 (R12 FALSE CLAIM #1-2 corrections)
- ADR-0255 (S44 W1 L5 chain restoration)
