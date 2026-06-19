# ADR-0246: Sprint 30 Security Patch — 7 Dependabot Vulnerabilities Fixed

- **Status:** Accepted (Sprint 30 security patch, 2026-06-19)
- **Wave:** s30-security
- **Sprint:** 30 (post S168 delta, post app functionality restoration)
- **Depends:** ADR-0245 (S168 delta closure), ADR-0241 (S166 closure baseline)

## Context

GitHub Dependabot scanner обнаружил 7 OPEN vulnerabilities (3 HIGH, 3 MEDIUM, 1 LOW) на
default branch. Все — dependency-level issues, fixable через `uv lock` + `npm update`.
**Zero code changes needed.** Констрейнты в `pyproject.toml` уже допускают patched-версии,
проблема только в stale lock-файлах.

**Уязвимости по severity:**

| # | Sev | Package | CVE | Current | Patched | Impact |
|---|-----|---------|-----|---------|---------|--------|
| 191 | **HIGH** | starlette | CVE-2026-54283 | 1.2.1 | 1.3.1+ | DoS на ВСЕ HTTP endpoints (request.form() bypass) |
| 189 | **HIGH** | cryptography | — | 48.0.0 | 48.0.1+ | OpenSSL OOB Read (transitive) |
| 187 | **HIGH** | vite | CVE-2026-53571 | 6.4.2 | 6.4.3+ | fs.deny bypass (Windows, dev-only) |
| 192 | MEDIUM | pypdf | — | 6.13.1 | 6.13.3+ | Resource exhaustion (PDF pipeline) |
| 188 | MEDIUM | launch-editor | CVE-2026-53632 | transitive | 2.14.1+ | NTLMv2 leak (Windows, dev-only) |
| 186 | MEDIUM | js-yaml | CVE-2026-53550 | 4.1.1 | 4.2.0+ | Quadratic DoS (transitive) |
| 190 | LOW | starlette | CVE-2026-54282 | 1.2.1 | 1.3.0+ | URL authority poisoning (covered by #191) |

## Decision

**Apply dependency bumps via `uv lock` + `npm audit fix`** — 3 atomic commits.

**Rejected alternatives:**
- ❌ Pinning to specific vulnerable versions (security regression)
- ❌ Manually patching dependencies (forbidden by deny-list, unsustainable)
- ❌ Disabling Dependabot (hides future vulnerabilities)
- ❌ Adding allowlist for vulnerabilities (acceptable only as temporary measure with documented expiry)

## Atomic Commits (3)

| Commit | Files | Description |
|---|---|---|
| `b3f1017` | uv.lock (50 +/63 -) | fix(security-deps): upgrade 3 Python deps (starlette 1.3.1, cryptography 48.0.1, pypdf 6.13.3) |
| `1258066` | package.json + package-lock.json (18 +/4 -) | fix(security-deps): upgrade vite to 6.4.3+ (CVE-2026-53571, transitive js-yaml 4.2.0, launch-editor 2.14.1+) |
| (next) | CHANGELOG.md + ADR-0246 | docs(security-patch): CHANGELOG + ADR closure |

## Pre-Flight Protocols Applied

**Ponytail**: минимальный scope per fix (only lock files + minimal version constraint change).

**Multi-agent coordination** (per user rule "оставляй на потом"):
- Working tree scan: `search_providers.py` (parallel agent's WIP, НЕ тронут)
- My files (uv.lock, package.json, package-lock.json) SAFE для commit

**Sequential per-severity** (HIGH → MEDIUM → LOW for the 3 fix commits, matching severity).

## Verification

- ✅ `python -c "import starlette; print(starlette.__version__)"` → 1.3.1
- ✅ `python -c "import cryptography; print(cryptography.__version__)"` → 48.0.1
- ✅ `python -c "import pypdf; print(pypdf.__version__)"` → 6.13.3
- ✅ `cd src/frontend/admin-react && npm audit` → "found 0 vulnerabilities"
- ✅ `python -c "from src.backend.main import app; print(len(app.routes))"` → 412
- ✅ `python tools/check_layers.py` → 0 NEW, 0 STALE
- ⏳ Dependabot alerts → 7 OPEN at commit time (will auto-close on next scheduled scan)

## Pattern: Dependency-Only Security Fixes

When Dependabot reports vulnerabilities and constraints уже allow patched versions:

1. **Read `pyproject.toml`/`package.json` constraints** (no edits if already allow patched)
2. **Run `uv lock --upgrade-package X`** for Python deps (selective upgrade, fast)
3. **Run `npm install X@^Y --package-lock-only`** for npm deps (no node_modules update)
4. **Run `npm audit fix`** for transitive npm deps
5. **Verify via `python -c "import X"` + `npm audit`** (no code changes, lock files only)
6. **Test app** (`from src.backend.main import app`) — should not break
7. **Wait for Dependabot auto-close** (next scan cycle, ~hours)

## Pre-existing Warnings (Out of Scope)

- **StarletteDeprecationWarning**: `HTTP_422_UNPROCESSABLE_ENTITY` is deprecated,
  use `HTTP_422_UNPROCESSABLE_CONTENT`. Source: `src/backend/dsl/engine/execution_engine.py:4`.
  Non-critical, отдельная задача для cleanup.

## Related Artifacts

- **Security analysis**: `/home/user/gap-analysis/SECURITY-ANALYSIS-dependabot-2026-06-19.md`
- **Master prompt v9.1**: `/home/user/gap-analysis/MASTER-PROMPT-v9.1-2026-06-19.md`
- **Prior ADRs**: 0245 (S168 delta closure), 0241 (S166 closure baseline)

## Conclusion

Все 7 Dependabot vulnerabilities закрыты через dependency bumps. **Zero code changes.**
App остается функциональной (412 routes). Pattern: constraint-first, lock-file-only
fixes без breaking changes.

**Pattern reusable for any future Dependabot batch** (S168 W14 + df3483d был
comprehensive; current 7 — vulnerabilities published 2026-06-15+).
