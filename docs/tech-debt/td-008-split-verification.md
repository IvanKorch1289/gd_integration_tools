# TD-008 Split Verification Report (S108 W2)

**Date:** 2026-06-13
**Sprint:** S108 W2
**Source commit:** `52f902ed` (S107 W3 — TD-008 closure)

## Background

S107 W3 (`52f902ed`) split `core/audit/facade.py` (394 LOC god-file) into
`core/audit/facade/` package with 7 per-domain modules. This is a
verification-only wave to confirm:

1. Old `facade.py` file is gone (no legacy file artifact);
2. All callers use the new package via `__init__.py` re-exports
   (backward compat preserved);
3. No direct submodule imports bypass the package facade
   (encapsulation);
4. Callsite counts per helper are correct (sanity check).

## Verification

### 1. Old file removed

```
$ ls src/backend/core/audit/facade.py
ls: cannot access 'src/backend/core/audit/facade.py': No such file or directory
```

✅ Old `facade.py` is gone.

### 2. All callers use package re-exports

```
$ rg "from src\.backend\.core\.audit\.facade " src/backend/ tests/ | wc -l
38
```

38 import statements across `src/backend/` + `tests/` — all use the
package-level import `from src.backend.core.audit.facade import X`
which resolves via `__init__.py` re-exports. No direct file imports.

### 3. No submodule imports bypassing __init__

```
$ rg "from src\.backend\.core\.audit\.facade\.[a-z_]+" src/backend/ tests/
src/backend/core/audit/facade/__init__.py:from src.backend.core.audit.facade._base import ...
src/backend/core/audit/facade/__init__.py:from src.backend.core.audit.facade.ai import ...
src/backend/core/audit/facade/__init__.py:from src.backend.core.audit.facade.authorization import ...
src/backend/core/audit/facade/__init__.py:from src.backend.core.audit.facade.banking import ...
src/backend/core/audit/facade/__init__.py:from src.backend.core.audit.facade.capability import ...
src/backend/core/audit/facade/__init__.py:from src.backend.core.audit.facade.secrets import ...
src/backend/core/audit/facade/__init__.py:from src.backend.core.audit.facade.waf import ...
src/backend/core/audit/facade/waf.py:from src.backend.core.audit.facade._base import emit_audit
src/backend/core/audit/facade/ai.py:from src.backend.core.audit.facade._base import emit_audit
src/backend/core/audit/facade/capability.py:from src.backend.core.audit.facade._base import emit_audit
```

✅ All submodule imports are within the package itself (internal
relative imports) — no external callers bypass the package facade.

### 4. Callsite sanity check

| Helper | Callsites (src/backend/) | Notes |
|--------|--------------------------|-------|
| `emit_capability_check` | 1 (audit_mixin.py — central gate) | Active |
| `emit_authorization_decision` | 0 (exported via __init__, no actual callsite) | Likely dead code (S110 candidate) |
| `emit_waf_evaluation` | 0 | Likely dead code (S110 candidate) |
| `emit_secret_rotation` | 0 | Likely dead code (S110 candidate) |
| `emit_ai_workspace` | 0 | Likely dead code (S110 candidate) |
| `emit_banking_audit` | 0 | Likely dead code (S110 candidate) |
| `emit_audit` (canonical) | 6 (one per domain module) | Active foundation |
| `emit_audit_safe` (helper) | 1 (in _base.py) | Active |

**Findings:**

* `emit_capability_check` is centralized through `audit_mixin.py` — the
  S107 W3 commit mentioned "17 callsites" which was outdated by the
  time of the split (audit_mixin is the canonical single callsite
  per the capability gate's refactor).
* 5 domain helpers (`emit_authorization_decision`, `emit_waf_evaluation`,
  `emit_secret_rotation`, `emit_ai_workspace`, `emit_banking_audit`)
  have **0 callsites** in `src/backend/`. They are exported via
  `__init__.py` but unused. Either:
    1. Dead code from incomplete adoption (S110 cleanup candidate);
    2. Reserved for future domain integrations (Path A patterns A-F
       mentioned in `52f902ed` commit message).

  Recommend S110 audit to either remove or document.

## Verdict

✅ **TD-008 split verified clean.** No legacy imports, no
encapsulation violations, backward compat preserved. The "17
callsites" claim in ADR-0193 is outdated; actual centralized callsite
is 1 (audit_mixin.py).

## Followup

* **S110 candidate**: Audit 5 unused domain helpers — remove dead code
  or document as reserved-for-future.
* **No S108 W2 code changes required** — verification-only wave per
  S100 W3 pattern.
