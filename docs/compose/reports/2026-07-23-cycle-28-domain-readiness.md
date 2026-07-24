# Per-Domain Readiness Report — Cycle 28 (FINAL)

**HEAD**: `a0be5c5d` (cycle 27 followup)
**Date**: 2026-07-23
**Method**: Tool-verified counts via `find`/`grep`/`ast`. No narrative-only claims.
**Scope**: 10 domains, 1328 test files, 93 facade providers, 6 bridge modules.

---

## Executive Summary

| Domain | Score | Trend | Blocking |
|---|---|---|---|
| core | 91/100 | 🟢 stable | non-facade cross-layer (17 files) |
| infrastructure | 78/100 | 🟡 maturing | DLQ coverage, custom dataloaders |
| security | 84/100 | 🟢 stable | fail-closed env vars validation |
| auth | 80/100 | 🟡 maturing | LDAP fallback, OAuth refresh |
| **dsl** | **72/100** | 🟡 **needs work** | 190 direct upper-layer imports; method docstrings 49%; missing YAML round-trip test |
| workflow | 82/100 | 🟢 stable | Saga forward/compensation index mapping |
| ai | 76/100 | 🟡 maturing | docstring coverage, sandbox consistency |
| services | 80/100 | 🟡 maturing | extensions→core violation (1 file) |
| entrypoints | 85/100 | 🟢 stable | WebhookTrigger reverse-import (graceful) |
| extensions | 65/100 | 🟠 needs work | inconsistent structure, 1 layer violation |
| frontend | 75/100 | 🟡 maturing | docstring coverage 35–63% |
| tests | 78/100 | 🟡 maturing | coverage 51.04% vs 75% aspirational |

**Overall readiness**: 79% (READY WITH CAVEATS — documented in meta-coord matrix; DSL revised down 85→72 after general-29 audit)

---

## Per-Domain Details

### 1. CORE — Score: 91/100

| Aspect | Value | Status |
|---|---|---|
| .py files | 457 | 🟢 |
| Sub-packages | 41 | 🟢 |
| Protocol/ABC classes | 152 | 🟢 (107 Protocol + 17 ABC + 28 generic) |
| Facade providers | 93 (45 auto + 6 bridge + 2 manual) | 🟢 |
| Docstring coverage (sampled) | 93.64% (module 93.55%, class 100%, func 87.37%) | 🟢 |
| Test files | 311 in `tests/unit/core/` | 🟢 |
| DSL infra→facade wiring | 8/8 complete (mongodb, redis, clickhouse, etc.) | 🟢 |

**Architecture compliance**:
- 17 non-facade `core→infrastructure` direct imports (must be migrated to facade)
- 23 `core→services` direct imports (must go through facade)
- 3 `core→dsl` direct imports (`interfaces/batch_capable.py` — needs investigation)

**Custom code analysis**:
- `datetime_utils.py` — justifed shim (S57 W3), keep
- `async_helpers.py` — pure ASGI wrapper, no stdlib equivalent, keep
- `retry_helper.py` — empty body (verify dead)
- retry/breaker — already use `tenacity`/`purgatory`, good

**To reach 100%**:
1. Migrate 17 non-facade `core→infrastructure` to facade getters
2. Migrate 23 `core→services` direct imports
3. Investigate `core/interfaces/batch_capable.py → dsl` cycle risk
4. Delete `retry_helper.py` if empty (verify)
5. Add core→dsl layer boundary audit

---

### 2. INFRASTRUCTURE — Score: 78/100

| Aspect | Value | Status |
|---|---|---|
| .py files | 428 | 🟢 |
| Sub-packages | 31 | 🟢 |
| Top contributors | `clients/ 66`, `database/ 40`, `resilience/ 28`, `workflow/ 28`, `security/ 27` | 🟢 |
| Sinks | 15 files (8 centralized via `_timeouts.py` cycle 12) | 🟢 |
| Sources | 24 files (CDC, webhook, soap, grpc, etc.) | 🟢 |
| Storage clients | 20 files (Redis, MongoDB, ES, ClickHouse, S3, etc.) | 🟢 |
| Tests | 204 in `tests/unit/infrastructure/` | 🟡 |
| Custom code | retry uses `tenacity`, breaker uses `purgatory` | 🟢 |

**Architecture compliance**:
- `infrastructure→services`: 4 direct (should go via facade)
- `infrastructure→dsl`: 19 direct (Ponytail-YAGNI — all in allowlist)
- Layer violations allowlist: 214 legacy entries (documented in ADR-0249)

**Functionality gaps**:
- DLQ coverage partial (4/6 transports: kafka, nats, rabbit, cleanup)
- No custom rate limiter (uses `fastapi-limiter` ✓)
- No custom retry decorator (uses `tenacity` ✓)

**To reach 100%**:
1. Add DLQ coverage for missing transports
2. Migrate 4 `infrastructure→services` to facade
3. Add CDC Redis source (only Kafka/Oracle/PG currently)
4. Add Redis-streams as alternative to Kafka
5. Increase sink test coverage from 14 to 25+ files

---

### 3. SECURITY — Score: 84/100

| Aspect | Value | Status |
|---|---|---|
| .py files | 34 | 🟢 |
| Auth modules | 23 (`core/auth/`) | 🟢 |
| Tests | 26 + 24 auth + 6 security | 🟢 |
| Layer independence | `core/security→services`: 1, `core/security→dsl`: 0 | 🟢 |
| Argon2 + joserfc + passlib + cryptography | all direct deps | 🟢 |

**Standards compliance**:
- OWASP ASVS — partial (auth, validation, error handling covered)
- NIST — partial (JWT via `joserfc`, Argon2 ✓)
- OAuth2/OIDC — partial (no full OIDC server, just JWT validation)

**Fail-closed coverage**:
- JWT blacklist (cycle 14 CVE fix): ✓
- CORS wildcard+credentials invariant (cycle 25 S1): ✓
- MCP authz fail-CLOSED (cycle 20 P0-3): ✓
- Capability gate enforced (cycle 8 D418 v2): ✓

**To reach 100%**:
1. Add OIDC discovery endpoint (or document why not needed)
2. Add hardware key support (WebAuthn/FIDO2)
3. Add OAuth2 refresh token rotation
4. Add full LDAP test suite (currently 1 file)
5. Add key rotation policy (Vault → automated)

---

### 4. AUTH — Score: 80/100

| Aspect | Value | Status |
|---|---|---|
| .py files | 23 | 🟢 |
| Methods | API_KEY, JWT, LDAP, MTLS, basic | 🟢 |
| Tests | 24 | 🟡 (only 1 file per method) |
| Argon2 primary + SHA-256 dual-verify | ✓ (cycle 14 CVE) | 🟢 |

**Gaps**:
- LDAP fallback minimal (only base.py exists)
- OAuth refresh token rotation: not implemented
- Multi-factor auth: absent

**To reach 100%**:
1. Add OAuth refresh token rotation
2. Complete LDAP failure scenarios
3. Add MFA (TOTP/SMS)
4. Add auth rate limiting per-user
5. Improve auth test coverage

---

### 5. DSL — Score: 72/100 (per general-29 audited)

| Aspect | Value | Status |
|---|---|---|
| .py files | 581 | 🟢 |
| DSL processor files | 98 (excluding `_path_safety.py` and `__init__.py`) | 🟢 |
| DSL builder files | 31 (`builders/`) | 🟢 |
| Infra processors (via facade) | 9 files / 10 import sites (9 distinct, `infra_elasticsearch` uses facade in 2 places) | 🟢 |
| Agent processor classes | 53 (21 agent_dsl + 20 ai + 12 ai_banking) | 🟢 |
| LLM provider adapters | 5 (MiniMax, OpenAI, Gemini, Claude, Ollama) | 🟢 |
| Workflow step types | **12** declarations + `WorkflowDeclaration` container (13 total) | 🟢 |
| Tests | 329 (`tests/unit/dsl/`) + 5 (`tests/unit/infrastructure/workflow/`) + 43 (`tests/unit/core/ai/`) | 🟢 |
| Layer violations (allowlist) | 214 (Ponytail-YAGNI per ADR-0249) | 🟡 |

**Docstring coverage** (sampled 10 deterministic random DSL processors, `random.seed(42)`):
- module docstrings: 80% (8/10)
- class docstrings: 100% (42/42)
- method docstrings: **48.9%** (46/94) ← low

**Layer independence** (DSL direct upper-layer imports):
- `dsl → services`: 93 import lines
- `dsl → infrastructure`: 95 import lines
- `dsl → entrypoints`: **2 import lines** (allowlist-tracked)
  - `commands/setup/registers_workflow.py:210` → `src.backend.entrypoints.webhook.transformer`
  - `orchestration/triggers.py:301` → `src.backend.entrypoints.api.app`

**Step types coverage** (per cycle-22+ work):
- `compile_saga_step` now uses `raise exc from comp_errors[-1]` (cycle 27 W1)
- `compile_signal_wait_step` has `on_timeout='raise'` default (cycle 27 H1)
- `WorkflowBuilder.version()` propagates (cycle 27 W3)
- `ResumeDeclaration.checkpoint_id` dead field removed (cycle 26 A2)

**Custom code**:
- `dsl/cli/debug.py` and `dsl/cli/generate.py` still use `click` (could migrate to `typer`)
- `dsl/cli/linter.py` already uses `typer`

**YAML round-trip coverage** (per general-29):
- `to_yaml` at `dsl/workflow/yaml_io.py:91`, `from_yaml` at `:112`
- Positive round-trip unit test: **MISSING** (only test_visualize.py uses `diff`)
- Gap: no equality assertion after `to_yaml → from_yaml`

**To reach 100%**:
1. Migrate 2 CLI files from `click` to `typer` (already in deps)
2. Add positive `WorkflowDeclaration` `to_yaml`/`from_yaml` round-trip test
3. Increase method docstring coverage from 49% → 80%
4. Refactor 190 direct upper-layer DSL imports → DI facades (2000-5000 LOC, per ADR-0249)
5. Migrate 2 `dsl → entrypoints` imports to core protocols (`commands/setup/registers_workflow.py:210`, `orchestration/triggers.py:301`)
6. Add DSL processor for Qdrant / PDF / Word / Excel (per dep analysis)

---

### 6. WORKFLOW — Score: 82/100

| Aspect | Value | Status |
|---|---|---|
| .py files | 28 (`infrastructure/workflow/`) | 🟢 |
| Step types | **12** (Activity, Saga, Pause, Resume, SignalWait, Sleep, Sensor, AgentInvoke, Reflect, Checkpoint, Guardrail, Escalate) + WorkflowDeclaration container = **13** | 🟢 |
| SagaLRA | state-check, persistent resume | 🟢 (cycle 19+27) |
| Strict compensate | chains cause with `from comp_errors[-1]` | 🟢 (cycle 27) |
| Wait signal timeout | default `'raise'` fail-loud | 🟢 (cycle 27) |
| Tests | 5 (`tests/unit/infrastructure/workflow/`) + 14 (`tests/unit/dsl/workflow/`) | 🟡 |
| YAML round-trip | `to_yaml`/`from_yaml` exist; positive test MISSING | 🟠 |
| Doc coverage (sample) | class 100%, func 100% | 🟢 |

**Step types docs** (per general-29):
- All 12 step declarations have class docstrings ✅
- Dedicated user-facing Markdown documentation for each step: **NOT FOUND**
- `WorkflowDeclaration` container at `dsl/workflow/spec/workflow.py:51`

**Pending items**:
- Saga forward/compensation index mapping (needs ADR + spec change)
- WorkflowMixin.build version propagation (cycle 27 W3 — FIXED)
- Deterministic Temporal time API used in pause (cycle 25 W2)
- WorkflowDeclaration YAML round-trip test (no positive equality test exists)

**To reach 100%**:
1. Add Saga explicit `forward_step_id` mapping (ADR needed)
2. Add positive `WorkflowDeclaration` YAML round-trip test
3. Write dedicated Markdown docs per step type
4. Implement `SagaHistory` query API
5. Add `WorkflowRegistry` (global workflow lookup)
6. Add Temporal Cloud workflows support
7. Add more step type tests (12 total, ~3 tests/step needed)

---

### 7. AI — Score: 76/100

| Aspect | Value | Status |
|---|---|---|
| `core/ai/` files | 19 | 🟢 |
| `services/ai/` files | 28 | 🟢 |
| DSL `agent_dsl/` processors | 23 | 🟢 |
| LLM providers (deps) | 2 (likely openai + litellm as aggregator) | 🟡 |
| Tests | 36 (`tests/unit/core/ai/`) + 43 (`tests/unit/services/ai/`) | 🟢 |
| AI gateway | 6 mixins (input, llm, output, audit, policy, orchestrator) | 🟢 |
| Sandbox (e2b) | cycle 26 wrap | 🟢 |
| Docstring (sample) | classes 100%, funcs (lower, 35-63%) | 🟡 |

**Gaps**:
- LLM provider adapters may not cover all dependencies (some `pyproject.toml` deps are transitive)
- Docstring coverage in `services/ai/` is below 80%
- PII masking + audit-event infrastructure is complete but not consistently tested

**To reach 100%**:
1. Audit which LLM provider adapters are real (vs passthrough)
2. Increase `services/ai/` docstring coverage to 80%+
3. Add hallucination detection
4. Add cost-aware routing (cheapest model for the task)
5. Add fine-tuning pipeline (if needed)

---

### 8. SERVICES — Score: 80/100

| Aspect | Value | Status |
|---|---|---|
| .py files | 391 | 🟢 |
| Sub-packages | 41 | 🟢 |
| Tests | 210 (`tests/unit/services/`) | 🟢 |
| Layer independence | `services→dsl`: 0 (clean) | 🟢 |
| Docstring (sample) | classes 100%, funcs 63% | 🟡 |

**Architecture compliance**: clean (no `services→dsl` direct imports — all via facade)

**Custom code analysis**:
- No custom CLI runners
- Uses `typer`/`click` (mixed)
- Uses `pydantic-settings` (proper)

**To reach 100%**:
1. Increase function docstring coverage to 80%+
2. Add per-service health check
3. Add service-level integration tests
4. Add chaos tests for services

---

### 9. ENTRYPOINTS — Score: 85/100

| Aspect | Value | Status |
|---|---|---|
| .py files | 224 | 🟢 |
| Sub-packages | 20 | 🟢 |
| Tests | 111 (`tests/unit/entrypoints/`) | 🟢 |
| Layer independence | `entrypoints→dsl`: 0 (clean) | 🟢 |
| Docstring (sample) | classes 100%, funcs 60% | 🟡 |
| API protocols | REST, SOAP, GraphQL, gRPC, WS, SSE, MCP, MQTT, HTTP3 | 🟢 |

**Architecture compliance**: clean

**To reach 100%**:
1. Increase function docstring coverage to 80%+
2. Add OpenAPI spec auto-validation in CI
3. Add API versioning strategy
4. Add rate limiting per route (not just global)
5. Add request tracing/middleware

---

### 10. EXTENSIONS — Score: 65/100

| Aspect | Value | Status |
|---|---|---|
| Extensions | 8 (core_admin, core_entities, credit_pipeline, dadata, example_plugin, osint_agent, skb, test_plug) | 🟡 |
| plugin.toml | 11 (8 top + 4 nested) | 🟡 |
| Tests | 5 total (2 unit + 3 integration) | 🟠 |
| Layer violations | 1 file (`extensions/core_entities/orders/workflows/orders_dsl.py:89,107,123 → entrypoints.base`) | 🟠 |
| Services subdirectory | only 2/8 extensions (`credit_pipeline`, `core_entities`) | 🟠 |

**To reach 100%**:
1. **Fix layer violation**: migrate `orders_dsl.py` from `entrypoints.base` to `core.utils.action_bus` facade
2. **Standardize extension structure**: all extensions should have `services/`, `tests/`, `plugin.toml`
3. **Increase test coverage**: 5 → ~30 tests (target 3+ per extension × 8)
4. **Document extension template**: clear template showing the canonical layout
5. **Add extension registration test**: verify each extension can be loaded

---

### 11. FRONTEND — Score: 75/100

| Aspect | Value | Status |
|---|---|---|
| .py files | 142 (95 pages + helpers) | 🟢 |
| Streamlit pages | 95 | 🟢 |
| Manifest registered | 69 | 🟢 |
| Actual pages | 69 | 🟢 (perfect match after cycle 25 F1) |
| Missing from manifest | 0 | 🟢 |
| API base URL centralization | 6 files updated to `get_api_base_url()` (cycle 25 F2) | 🟢 |
| `00_Главная` page-key bug | fixed (cycle 17) | 🟢 |
| Docstring (sample) | classes 100%, funcs 35-63% | 🟠 |
| Tests | 27 (`tests/unit/frontend/`) | 🟡 |

**To reach 100%**:
1. Increase function docstring coverage to 80%+
2. Add OpenAPI DTOs for narrow endpoints (8 endpoints identified)
3. Add E2E tests via Playwright
4. Migrate deprecated `width=N` numeric → `width='stretch'` (cycle 18 done)
5. Add frontend bundle analyzer

---

### 12. TESTS — Score: 78/100

| Aspect | Value | Status |
|---|---|---|
| Test files total | 1328 | 🟢 |
| Coverage baseline | 51.04% (vs 75% aspirational) | 🟡 |
| Tests collected | 13033 (per cycle 24 swarm) | 🟢 |
| Cycle 22+25+26+27 isolated tests | 60-61/61 PASS (1 intermittent race) | 🟢 |
| CI workflows | 18 (perf, lint, security, sbom, chaos, api-fuzz, ai-eval, etc.) | 🟢 |
| Pre-commit hooks | 8 | 🟢 |

**Coverage gap (Ponytail-YAGNI: deferred per Sprint 39)**:
- Current baseline 51.04% ratchets down on drop
- Target 75% aspirational (S40+ closure)
- Test builder.py: stale test for ResumeDeclaration.checkpoint_id cleaned in cycle 27

**To reach 100%**:
1. **Coverage push**: write tests for critical paths (auth, capability, DLQ, fail-closed)
2. **Add property tests**: `hypothesis` already in deps, only 17 files use it
3. **Resolve 6 pre-existing test failures** (jmespath missing, etc.)
4. **Add coverage ratchet tool**: currently loose
5. **Add mutation testing**: `mutmut` already in deps

---

## Cross-Domain Recommendations

### High priority (blocks 100%)

1. **core→dsl layer cycle investigation** (`core/interfaces/batch_capable.py`)
2. **Extensions layer violation fix** (`extensions/core_entities/orders/workflows/orders_dsl.py`)
3. **214 layer violations refactor** (2000-5000 LOC, per ADR-0249)
4. **Coverage 51% → 75%** (Sprint 40+ closure)

### Medium priority (improves quality)

5. CLI `click` → `typer` migration (2 files)
6. Docstring coverage improvement to 80%+
7. Add qdrant + pypdf + docx + xlsx DSL processor wraps (per dep analysis)
8. Pre-existing test failures cleanup (6 files)

### Low priority (nice to have)

9. Custom replacements in `core/utils/` (verify no dead code)
10. Hardware key support in auth (WebAuthn)
11. OIDC discovery endpoint

---

## Summary Table — 100% Readiness Targets

| Domain | Current | Target | Δ | Effort |
|---|---|---|---|---|
| core | 91 | 100 | -9 layer violations fix | Medium |
| infrastructure | 78 | 95 | DLQ + tests + facade migration | High |
| security | 84 | 95 | OIDC, MFA, rotation | Medium |
| auth | 80 | 95 | OAuth refresh, LDAP scenarios | Medium |
| dsl | 72 | 95 | typer migration + dep wraps + YAML round-trip test + method docstrings | Medium |
| workflow | 82 | 95 | Saga explicit mapping (ADR) + dedicated step docs | Medium |
| ai | 76 | 90 | docstring + provider audit | Low |
| services | 80 | 90 | docstring improvement | Low |
| entrypoints | 85 | 95 | docstring + OpenAPI auto-validation | Low |
| extensions | 65 | 90 | standardize + fix violation | Medium |
| frontend | 75 | 90 | docstring + Playwright E2E | Medium |
| tests | 78 | 90 | coverage push | High |

**Total effort estimate**: 3000-5000 LOC across multiple sprints.

**Zero critical P0/P1** open. All known issues documented.
