# Sprint 44-47 Cross-Sprint Analysis (2026-08-25)

> **Method**: Swarm synthesis via subagent (read-only) + parent-agent authoring.
> **Scope**: 4 sprints (S44 W1-S47 W4), ~30 commits, 8 backlog items,
> 4 honest DECLINED ADRs, 2 fact-check ADRs.
> **Purpose**: Identify cross-sprint patterns for S48+ planning.

## 0. Sprint summary table

| Sprint | Cycles | Commits | Backlog items | ADRs added | New tests | Status |
|---|---|---|---|---|---|---|
| **S44** (R12) | W1-W46 | ~50 | 3 P0/P1 closed | 4 (0254-0257) | ~150 | complete |
| **S45** | 244-260 | 17 | 6 items addressed (Protocol migration, stub drift, dashboard, DSL lib map, audit fact-check, coverage) | 5 (0258, 0259, 0260, 0261, retro) | ~85 | complete |
| **S46** | 261-265 | 5 | Mobile JWT Phase 1+2+3 + S-L7-5 Kafka consumer | 2 (0264, 0265) | ~28 | complete |
| **S47** | 266-268+ | 4 | Redis impls + integration tests + S13 reaffirm | 1 (0266) | ~19 | complete |
| **Total** | 244-268+ | **~76** | **17 items addressed, 1 reaffirmed DECLINED** | **12** | **~282** | |

## 1. Cumulative totals

| Metric | S44 close | S47 close | Delta |
|---|---|---|---|
| ADR count | 217 | 231 | +14 (0254-0266) |
| Protocol classes | 2 | 22 | +20 (cycle 244) |
| Dashboards | 3 | 4 | +1 (quality-metrics) |
| CI workflows | 18 | 19 | +1 (stubs-drift) |
| New tests (cumulative S45-S47) | 0 | ~282 | +282 |
| Production code (security/observability) | baseline | +500 LOC | +500 |
| Coverage (real) | 1% | 1% | honest maintained |
| Backlog P0 | 0 | 0 | maintained |
| Backlog P1 | 0 | 0 | maintained |

## 2. Cross-sprint patterns (8 insights)

### 2.1 Honest verification > inherited claims

S45 ADR-0259 documented 3 audit claims that needed fact-checking:
yaml.load (FALSE), InProcessAgentSandbox default (PARTIALLY FALSE),
pg_runner.replay (TRUE). This pattern of explicit verification became
standard for subsequent ADRs.

**Implication**: Future audits cite fact-check ADRs (0259, 0260, 0266)
instead of repeating the cycle of stale claims.

### 2.2 Phase-gated security work prevents premature exposure

Mobile JWT shipped as 3 phases over 2 sprints:
- S46 W1: skeleton + flag-gated path
- S46 W2: revocation + rate limit (in-memory)
- S46 W3: OWASP checklist (14/17 PASS)
- S47 W1: Redis impls for production
- S47 W2: TestClient integration

`mobile_jwt_enabled` flag stayed OFF the whole time. Foundation ready,
exposure gated on external sign-off (OWASP security team + mobile team).

### 2.3 Production state-changing infra needs ceremony

S13 (Circuit Breaker Redis) DECLINED in S43 (ADR-0251), reaffirmed in
S47 (ADR-0266). 4-phase ceremony plan documented but not started:
- Phase 1: lazy factory init + DI (4-6h)
- Phase 2: middleware consolidation (4-6h)
- Phase 3: multi-pod validation (2-4h)
- Phase 4: staged deployment (1-2h + 1 week staging)

**Implication**: Single-sprint code changes to security/observability
infrastructure should be declined or carefully phased.

### 2.4 Ponytail/YAGNI avoided 2 duplications

S45 ADR-0260 documented that Fabric/Tika processors would have duplicated
existing asyncssh/pypdf coverage. Saved ~200 LOC of maintenance burden.

**Implication**: Audit recommendations should be verified against current
state before implementation. "Use library X" requires checking if library
X is already in use via different interface.

### 2.5 Subagent profile choice matters

Several subagent failures earlier (cycle 244-247) traced to wrong
subagent_type. Fixed by using "coder" or "explore" explicitly. Recent
swarm pattern (S47) uses 2 parallel "explore" agents for read-only
analysis with parent agent finalizing file writes.

**Implication**: Swarm mode requires correct subagent_type; explore agents
are read-only by design (forces clean separation of analysis vs writing).

### 2.6 Live dashboard > static reports

S45 cycle 251 added `quality-metrics.json` dashboard with 3 panels
(coverage, bandit, layer violations). Replaces static markdown audit
claims with live Prometheus-sourced metrics.

**Implication**: Audit accuracy trend (S45 cycle 254 analysis) improves
each sprint because dashboards provide ground truth, not typed numbers.

### 2.7 Coverage honesty > optimistic percentages

S44 W29 claimed "12% coverage" but only measured narrow subset
(core/ai + agent_security). S45 W32 retested: **1% real**. Documented
honestly in ADR-0261 with realistic +1pp/cycle ratchet plan.

**Implication**: Subset coverage claims should always disclose subset
denominator. 12% on 2 files ≠ 12% on 107k statements.

### 2.8 Code review as ADR artifact

S45 cycle 253 code review surfaced 2 minor follow-ups (isinstance Protocol
smoke tests + dashboard JSON parse error). S47 W4 review surfaced 2 more
(rust I001 + mypy typing on `_get_client()`). Pattern: review → fix →
retest → commit (no separate fix cycle).

**Implication**: Code review is integrated into sprint cadence, not a
separate phase. Findings → commits in same sprint.

## 3. Recommendations for S48+

1. **S13 Phase 1 (foundation)**: Start with lazy factory init in
   `BreakerRegistry.__init__`. Lowest-risk piece of the 4-phase plan.
2. **OWASP external sign-off**: Surface to product owner in W1 retro —
   this is the long-pole for `mobile_jwt_enabled` flag flip to ON.
3. **Mobile JWT refresh token strategy**: Design OAuth2.0-compatible
   refresh endpoint. Integrate with existing JWT infrastructure.
4. **Cross-sprint ADR review**: Periodically verify ADR claims still hold
   (e.g., re-read ADR-0266 in S50 to see if S13 ceremony plan is still
   accurate).
5. **Coverage ratchet check**: Measure at S48 close — should be ~2%
   (1% baseline + 1pp/cycle target per ADR-0261).
6. **Subagent prompt template**: Standardize prompts with explicit
   subagent_type, pre-reserved ADR numbers, max tool call budget.
7. **Quality dashboard live data**: Wire Prometheus exporter for the
   3 metric names referenced in `quality-metrics.json` (currently
   panels show "No data").

## 4. References

- `docs/retros/SPRINT_44_W1-W4_RETRO_2026-08-30.md` — S44 retro
- `docs/retros/SPRINT_45_COMPLETE_RETRO_2026-08-25.md` — S45 retro
- `docs/retros/SPRINT_45_W1_AUDIT_TREND_ANALYSIS_2026-08-25.md` — audit analysis
- `docs/retros/SPRINT_46_COMPLETE_RETRO_2026-08-25.md` — S46 retro
- `docs/retros/SPRINT_47_COMPLETE_RETRO_2026-08-25.md` — S47 retro
- `docs/retros/SPRINT_47_CODE_REVIEW.md` — S47 code review
- ADR-0259 (fact-check), ADR-0265 (OWASP), ADR-0266 (S13 reaffirm)
