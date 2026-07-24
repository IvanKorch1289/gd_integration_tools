# Sprint Plan — Next Cycle (Post Cycle 30)

**Date**: 2026-07-24
**Previous**: Cycles 25-30 (Master Prompt 24/24 closed, 82% readiness)
**Goal**: Reach 90%+ domain readiness through targeted improvements

---

## Current State (verified 2026-07-24)

| Domain | Score | Key Gap |
|---|---|---|
| core | 91 | 17 non-facade cross-layer imports |
| infrastructure | 78 | DLQ coverage, 4→services direct |
| security | 84 | OIDC, MFA, OAuth refresh |
| auth | 80 | LDAP failure scenarios, MFA |
| dsl | 78 | 96 flat files, method docstrings 70% |
| workflow | 88 | Saga explicit mapping (ADR needed for full impl) |
| ai | 76 | Docstring coverage, LLM provider audit |
| services | 80 | Docstring 63%→80% |
| entrypoints | 85 | Docstring 60%→80%, OpenAPI auto-validation |
| extensions | 72 | Structure standardization, +25 tests |
| frontend | 75 | Docstring 35-63%, Playwright E2E |
| tests | 82 | Coverage 51%→75%, 6 pre-existing failures |

**Overall: 82%**

---

## Sprint Goals (priority-ordered)

### S1: Coverage Push (High effort, High impact)

**Goal**: Coverage 51% → 65% (incremental toward 75%)

**Tasks**:
- [ ] Write tests for critical auth paths (API key verify, JWT blacklist, MTLS handshake)
- [ ] Write tests for capability gate enforcement (all 8 BaseProcessor subclasses)
- [ ] Write tests for DLQ writer (Kafka/NATS/RabbitMQ — 4 transports)
- [ ] Write tests for sink fail-closed paths (CDC/MCP/RPA/SOAP — cycle 20 fixes)
- [ ] Write property-based tests for DSL pipeline round-trip (hypothesis)
- [ ] Resolve 6 pre-existing test failures (missing deps: prometheus_client, purgatory)

**Effort**: 3-5 days
**Metric**: `.baselines/coverage.json` → 65%+

---

### S2: DSL Processors Directory Split (Medium effort, Medium impact)

**Goal**: Move 96 flat processors into domain subdirs (additive pattern)

**Tasks**:
- [ ] Create `ai/` subdir (move ai_*.py, ai_rpa.py, ai_rlm.py)
- [ ] Create `workflow/` subdir (move *_workflow*.py, saga_lra.py, hitl_approval.py)
- [ ] Create `cdc/` subdir (move cdc_*.py)
- [ ] Create `integration/` subdir (move integration*.py, external.py, web.py)
- [ ] Create `streaming/` subdir (move streaming*.py)
- [ ] Each subdir gets `__init__.py` with re-exports (additive, non-breaking)
- [ ] Update `check_layers_allowlist.txt` if needed

**Effort**: 2-3 days
**Pattern**: Established in cycle 30 (db/ subdir)

---

### S3: Docstring Coverage Push (Low effort per file, High volume)

**Goal**: 80%+ docstring coverage across all domains

**Tasks**:
- [ ] DSL processors: 49% → 80% (cycle 28 started, ~30 files need docstrings)
- [ ] Services: 63% → 80% (~20 files need function docstrings)
- [ ] Frontend: 35-63% → 80% (~40 files need docstrings)
- [ ] Entrypoints: 60% → 80% (~15 files need function docstrings)

**Effort**: 2-3 days (can parallelize across agents)
**Tool**: `make check-docstrings --summary` (already exists)

---

### S4: Extensions Standardization (Medium effort, Medium impact)

**Goal**: All 8 extensions follow consistent structure

**Tasks**:
- [ ] Audit each extension for `plugin.toml`, `services/`, `tests/` presence
- [ ] Add `tests/` to 6 extensions missing test coverage
- [ ] Standardize directory naming (`domain/` vs `services/` vs root)
- [ ] Add `__init__.py` re-exports for each extension's public API
- [ ] Document extension template (README or CONTRIBUTING.md)

**Effort**: 2-3 days

---

### S5: Security Hardening (Low effort, High impact)

**Goal**: Close remaining security gaps

**Tasks**:
- [ ] Add OAuth2 refresh token rotation
- [ ] Add MFA (TOTP) support in auth backend
- [ ] Add per-user auth rate limiting
- [ ] Add OIDC discovery endpoint (or document why not needed)
- [ ] Add WebAuthn/FIDO2 support (stretch goal)

**Effort**: 3-5 days

---

### S6: RouteBuilder Composition Migration (High effort, High impact)

**Goal**: Begin gradual migration from mixin MRO to Protocol composition

**Tasks**:
- [ ] Implement `CompositionRouteBuilder` alongside `RouteBuilder`
- [ ] Migrate 1-2 extensions to use CompositionRouteBuilder
- [ ] Add ADR documenting the composition pattern
- [ ] Benchmark: ensure no performance regression

**Effort**: 1-2 weeks (multi-sprint)
**Prerequisite**: Protocol definitions (cycle 30 P4-#4, already done)

---

## Risk Assessment

| Risk | Probability | Impact | Mitigation |
|---|---|---|---|
| Coverage push finds new bugs | High | Medium | Fix as found (no backlog) |
| DSL split breaks imports | Medium | High | Additive pattern (re-exports) |
| RouteBuilder migration breaks callers | High | Critical | Parallel impl, gradual migration |
| Extensions refactor breaks plugin loading | Medium | High | Test each extension after change |

---

## Definition of Done (per sprint item)

1. Code change + unit test (both PASS)
2. `py_compile.compile` on all changed files
3. `make lint` (soft) + `make vulture-gate` (strict)
4. CHANGELOG entry with "What we explicitly did NOT do"
5. Conventional commit message
6. Docstring for any new public API

---

## References

- DEEP_AUDIT_REPORT.md (2026-06-22 baseline)
- CHANGELOG.md (S203 section, cycles 25-30)
- docs/compose/reports/2026-07-23-cycle-28-domain-readiness.md (12-domain audit)
- docs/compose/reports/2026-07-23-cycle-29-master-prompt-coverage.md (24/24 closure)
- docs/adr/0249-dsl-upper-layer-imports-debt.md (layer violations ADR)
