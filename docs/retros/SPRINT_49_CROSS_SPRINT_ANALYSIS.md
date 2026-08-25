# Sprint 44-49 Cross-Sprint Analysis (2026-08-25)

> **Method**: Parent-agent analysis (swarm unreliable in S48).
> **Scope**: 6 sprints (S44-S49), 6 retro docs, 13 ADRs.

## 0. Sprint summary table

| Sprint | Cycles | Commits | Focus | Key outcome |
|---|---|---|---|---|
| **S44** | W1-W46 | ~50 | God-object refactor + P0 closure | 5/5 god-objects DONE, L5 chain + 19 tests |
| **S45** | 244-260 | 17 | Audit cleanup + coverage honesty + tools | Protocol migration 22/22, stub drift CI, dashboard |
| **S46** | 261-265 | 5 | Mobile JWT Phase 1-3 + S-L7-5 | MobileJwtVerifier + 14 tests + OWASP review |
| **S47** | 266-269 | 4 | Mobile JWT Redis + integration + S13 reaffirm | Redis impls + 13 tests + S13 ceremony plan |
| **S48** | 270-272 | 3 | S13 Phase 1 foundation + refresh endpoint | BreakerRegistry Redis support + 7 tests + Phase 2 ADR |
| **S49** | 273-275 | 3 | S13 Phase 2a + flag + refresh JWT | BreakerPolicyAdapter + flag + refresh JWT + 22 tests |

**Total**: ~82 commits, ~330 new tests, 13 ADRs, 6 retro docs

## 1. Cumulative metrics

| Metric | S44 close | S49 close | Delta |
|---|---|---|---|
| ADR count | 217 | 235 | +18 (0254-0269 + 2 retro) |
| Protocol classes | 2 | 22 | +20 |
| Production code (security/resilience) | baseline | +5 modules | +5 |
| New tests (cumulative S45-S49) | 0 | ~330 | +330 |
| CI workflows | 18 | 19 | +1 (stubs-drift) |
| Dashboards | 3 | 4 | +1 (quality-metrics) |
| Endpoints added (mobile) | 1 | 2 | +1 (/auth/refresh) |
| Coverage (real) | 1% | 1% | honest maintained |
| Production readiness | 96% | 96% | maintained |

## 2. Cross-sprint patterns (10 insights)

### 2.1 Honest verification > inherited claims (S45)

ADR-0259 fact-checked 3 audit claims. This pattern became standard: every
audit claim needs grep + Read verification before being cited.

### 2.2 Phase-gated security work (S46-S47)

Mobile JWT shipped as 4 phases over 2 sprints:
- Phase 1: skeleton (S46 W1)
- Phase 2: revocation + RL in-memory (S46 W2)
- Phase 3: OWASP review (S46 W3)
- Phase 4: Redis impls (S47 W1)
- Phase 5: integration tests (S47 W2)

`mobile_jwt_enabled` flag stayed OFF the whole time.

### 2.3 Production state-changing infra needs ceremony (S45-S49)

S13 (Circuit Breaker Redis) DECLINED in S43 (ADR-0251), reaffirmed in S47
(ADR-0266), Phase 1 foundation shipped in S48 W1 (cycle 270), Phase 2a
foundation shipped in S49 W1 (cycle 273). 4-phase rollout plan documented
(ADR-0268) — still needs Phase 2b (wiring) + Phase 3 (multi-pod).

### 2.4 Ponytail/YAGNI avoided 2 duplications (S45)

ADR-0260 documented that Fabric/Tika processors would have duplicated
existing asyncssh/pypdf coverage. Saved ~200 LOC.

### 2.5 Subagent profile choice matters (S47-S48)

Swarm agents using `explore` profile can't write files (read-only).
Pattern: parent agent finalizes all docs from subagent reports.
In S48 swarm failed entirely (silent timeouts). Lesson: parent-agent
direct execution more reliable for small/medium scopes.

### 2.6 Live dashboard > static reports (S45)

`quality-metrics.json` (cycle 251) replaces static markdown with live
Prometheus-sourced panels. Future audits read dashboard, not stale docs.

### 2.7 Coverage honesty > optimistic percentages (S45)

W29 "12% coverage" was narrow subset. Full project: 1%. Sprint 45 ratchet
plan (ADR-0261) targets +1pp/cycle honest climb.

### 2.8 Code review as ADR artifact (S45-S49)

Reviews surface findings → commits in same sprint. Pattern: cycle N
work + cycle N review + cycle N+1 follow-up.

### 2.9 When in doubt, INVESTIGATE → ADR rather than half-implement (S48)

S48 W3 originally planned middleware refactor. Investigated scope (6-10h,
4 phases), produced ADR-0268 documenting the path. Better than shipping
half-done refactor.

### 2.10 Bug found + fixed during testing (S49)

Cycle 275 initial draft of refresh code was missing
`from src.backend.core.config.features import feature_flags` line.
DEBUG log technique caught it immediately. **Lesson**: always verify
imports when copying patterns across endpoints.

## 3. Recommendations for S50+

1. **S13 Phase 2b wiring**: Now that Phase 2a foundation is in place,
   S50 should wire the middleware to use adapter when flag is ON.
   Test with feature flag first, then remove legacy _legacy_states.

2. **OWASP external sign-off**: Surface to product owner in S50 W1 retro.
   This is the long-pole for `mobile_jwt_enabled` flag flip to ON.

3. **S13 Phase 3 multi-pod integration tests**: Set up 2 pod test
   environment with shared Redis. Verify cross-pod breaker state.

4. **Coverage ratchet**: Measure at S50 close — should be ~2% (1% + 1pp).

5. **Prometheus exporter for quality-metrics.json**: Wire the 3 metric
   names referenced in `quality-metrics.json` (currently panels show
   "No data").

6. **Subagent prompt template**: Standardize with pre-reserved ADR
   numbers, max tool call budget, explicit subagent_type.

## 4. References

- `docs/retros/SPRINT_44-47_CROSS_SPRINT_ANALYSIS.md` — earlier analysis
- `docs/retros/SPRINT_48_COMPLETE_RETRO_2026-08-25.md` — S48 retro
- ADR-0259 (fact-check), ADR-0261 (ratchet), ADR-0268 (S13 plan),
  ADR-0269 (Phase 2a)
