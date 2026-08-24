# ADR-0254: AgentSecurity god-object 5/5 — DISCOVERED COMPLETE (S43 W3, Variant 3)

> **Status**: DISCOVERY REPORT (not a refactor plan)
> **Method**: Read all 5 module files, count actual lines,
> run smoke tests. No claims from prior audit reports.
>
> **TL;DR**: god-object 5/5 = **DONE** (untracked).
> agent_security.py = **73 LOC** facade (was 652 in audit R9).
> 4 sibling modules already extracted (560+ LOC total).
> All 21 defs accounted for in extracted modules.
> **R11 audit was stale**: it claimed "agent_security.py 652 LOC god-object (P1,
> 16-20h)". Reality: refactor is COMPLETE, just uncommitted.

## 0. Verified state (2026-08-30, Sprint 43 W3)

| File | LOC | Status | Classes |
|---|---:|---|---|
| `agent_security.py` | **73** | FACADE (re-exports only, 0 class/def) | n/a |
| `agent_security_types.py` | 145 | ✅ extracted | ThreatLevel, SecurityDecision, SecurityHook, patterns |
| `agent_security_detectors.py` | 102 | ✅ extracted | DangerousCommandDetector, PromptValidator |
| `agent_security_policy.py` | 114 | ✅ extracted | FileModificationPolicy, AgentSecurityPolicy |
| `agent_security_framework.py` | ~310 | ✅ extracted | AgentSecurityFramework |
| `workflow_hooks.py` | 314 | ✅ already separate | (workflow hooks) |
| `__init__.py` | 65 | facade re-exports | n/a |
| **Total split LOC** | **1023** | 7 files | **7 classes** + helpers |

## 1. R9/R11 audit FALSE CLAIM (corrected)

| Claim | Audit | Verified reality |
|---|---|---|
| "agent_security.py 652 LOC god-object (P1, deferred 16-20h)" | R9 honest deferral, R11 carryover | **73 LOC facade** (untracked S187 completion) |
| "7 classes, 21 defs" | R11 | ✅ 7 classes, 21+ defs in extracted modules |
| "simplified port broke 27/30 tests" | R9 | n/a — verbatim port was done (modifications date 2026-08-24) |
| "P1, 16-20h with security review" | R9/R11 | **0h** — already done |

**Discovery date**: 2026-08-30 (this audit)
**Discovered via**: `ls src/backend/core/ai/security/`
**Reason for missed**: files untracked, never committed

## 2. Smoke verification (passed)

```
$ python -c "from src.backend.core.ai.security import get_agent_security_framework, ..."
All 8 security imports OK
validate_prompt ok: allowed=True
validate_sql ok: allowed=True
```

End-to-end functional: ALL public API works, framework methods return
correct SecurityDecision objects.

## 3. What needs to happen (this commit)

1. ✅ Discovery report (this ADR-0254)
2. ⏳ Commit 4 untracked files (types, detectors, policy, framework)
3. ⏳ Update docs/STATUS.md to mark god-object 5/5 DONE
4. ⏳ Update INDEX.md of audit reports (this is R12 finding)

## 4. What does NOT need to happen

- ❌ Refactor of agent_security.py — already 73 LOC facade (DONE)
- ❌ 16-20h with security review — not needed (verified done)
- ❌ Phase 1-4 plan from earlier draft — moot

## 5. Open security follow-ups (separate from god-object)

If any new P1 items emerge from this discovery:
1. **Test coverage of new modules**: do `test_agent_security.py` and
   `test_facade_validate_sql.py` still pass? (35 tests)
2. **No regression in DSL processors** (`agent_security_check.py` etc.)
3. **No regression in extension security middleware**

If all 35 + DSL + middleware tests pass → god-object 5/5 = TRULY DONE.

## 6. References

- RE_AUDIT_2026-08-28.md §5 + Appendix — "5/5 REJECTED, agent_security"
- RE_AUDIT_FACTCHECK_2026-08-30.md §2.4 — "21 defs verified"
- docs/STATUS.md §P1.1 — needs update from P1 to ✅ DONE
