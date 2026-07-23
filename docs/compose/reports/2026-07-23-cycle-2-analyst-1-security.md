# Cycle 2 — Analyst 1 (Security) — Consolidated

**Status**: success
**Files scanned**: 143 .py (core/security, core/auth, core/audit, infrastructure/security, services/security, services/authorization, entrypoints/middlewares — non-security)

## Summary
- 6 P0 misplaced-module-docstring instances
- 3 P2 assert-as-type-narrowing sites
- 0 hardcoded secrets, 0 shell injection, 0 PII logging, 0 unsafe deserialization, 0 capability bypass

## P0 findings (all NEW)

1. `src/backend/core/security/capabilities/vocabulary/models.py:7`
2. `src/backend/core/security/capabilities/vocabulary/defaults.py:16`
3. `src/backend/core/security/capabilities/gate/audit_mixin.py:7`
4. `src/backend/core/security/capabilities/gate/cache_mixin.py:7`
5. `src/backend/core/security/capabilities/gate/check_mixin.py:7`
6. `src/backend/core/security/capabilities/gate/declaration_mixin.py:7`

Pattern: `from __future__ import annotations` on L1, then non-future imports, then `"""docstring"""` after. Module's `__doc__` resolves to `None`. PEP 257 violation.

## P2 findings (style only)
- `core/security/capabilities/gate/check_mixin.py:157` — `assert declared.scope is not None`
- `core/auth/jwks_cache.py:101,106` — `assert self._cache is not None`
- `core/auth/jwt_backend.py:224,227` — `assert self.secret is not None` / `assert self.jwks is not None`

Stripped under `python -O`. Recommended: explicit raise or `typing.cast`.

## Detected clean (negative findings)
- All 20 `except Exception:` are fail-closed defensive branches
- Secret handlers log only paths + exception types (no values)
- No eval/exec/yaml.load/pickle.loads anywhere
- `@require_capability` always raises (fail-closed)
- No hardcoded `/tmp|/etc|/root` runtime paths (only docstring examples)

## Pattern worth promoting project-wide
Misplaced-module-docstring likely reproduces outside Security in `dsl/`, `services/`, `ai/`, etc. Cheap detector: `ast.parse` + check `Expr(Constant(str))` position in `tree.body`.
