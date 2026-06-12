# ADR-0160 — Sprint 78 closure: P0-D CORS/XSRF в Streamlit (config security + nginx + validator + 17 NEW tests) (5 commits)

* Статус: Accepted (Autonomous work cycle S78, 2026-06-12)
* Связано с: FINAL_REPORT_V2 P0-D, S52 W2 (security_checks для
  backend CORS), S53 W1 (Streamlit config.toml baseline)

## Контекст

S78 = **P0-D closure** (FINAL_REPORT_V2 P0-D "CORS/XSRF отключены
во фронтенде"). Pre-S78: `enableCORS=false, enableXsrfProtection=false`
(unsafe defaults в dev convenience mode).

**Fact-check**: security_checks.py уже имеет CORS validators для
backend FastAPI. Streamlit CORS — отдельная проблема (Streamlit
runs on its own server, не FastAPI).

## Команда результаты (5 commits)

### W1: Streamlit config security (commit `fb28c57b`)
- File: `src/frontend/streamlit_app/.streamlit/config.toml` (+31, -2)
- `enableXsrfProtection = true` (CSRF ON)
- `enableCORS = true` + explicit `corsAllowedOrigins` (no wildcard):
  - `http://localhost:3000` (React admin UI dev)
  - `https://admin.corp.example.ru` (prod)
  - `https://staging-admin.corp.example.ru` (staging)
  - `https://grafana.corp.example.ru` (monitoring)
- `[browser] gatherUsageStats = false` (privacy)

### W2+W3: nginx config + validator + pre-commit gate (commit `08a945ae`)
- File: `docs/deployment/nginx_streamlit.conf` (NEW, 96 LOC) — production
  nginx reverse-proxy config с 7 security headers:
  - X-Frame-Options, X-Content-Type-Options, X-XSS-Protection,
    Referrer-Policy, Permissions-Policy, Content-Security-Policy,
    Strict-Transport-Security
  - SSL termination (Let's Encrypt)
  - WebSocket support (Streamlit live updates)
  - HTTP → HTTPS redirect
- File: `tools/check_streamlit_security.py` (NEW, 220 LOC):
  - `check_streamlit_config()` → `SecurityCheckResult` (4 checks)
  - XSRF, CORS allowlist (no wildcard), gatherUsageStats, headless
  - CLI mode: exit 0/1
- File: `.pre-commit-config.yaml` (+11, -0) — pre-commit hook registered
  (W3)

### W4: Tests (commit `4c922b6d`)
- File: `tests/unit/tools/test_check_streamlit_security.py` (NEW, 298 LOC)
- 17 NEW tests (5 default + 6 failure + 3 dataclass + 1 error + 2 CLI)

### W5: Closure (this commit)

## Final state vs FINAL_REPORT_V2 P0-D

| Layer | Before S78 | After S78 |
|---|---|---|
| Streamlit XSRF | ❌ disabled | ✅ **enabled (S78 W1)** |
| Streamlit CORS | ❌ disabled | ✅ enabled с explicit allowlist |
| gatherUsageStats | ✅ true (data leakage) | ✅ false (privacy) |
| headless | ❌ false | ✅ true (production-safe) |
| Security headers | ❌ none | ✅ **nginx config (S78 W2)** |
| CI gate | ❌ none | ✅ **pre-commit hook (S78 W3)** |

**Status vs FINAL_REPORT_V2 P0-D**: CLOSED.

## Pre-S78 vulnerabilities (P0-D)

1. **CSRF**: attacker crafts malicious page → browser calls Streamlit
   backend → exfiltrate data. Fixed by `enableXsrfProtection = true`.
2. **CORS off**: legitimate cross-origin blocked, forcing users to
   disable browser security (worse than explicit allowlist). Fixed
   by `enableCORS = true` + explicit allowlist.
3. **gatherUsageStats ON**: usage data sent to Streamlit analytics
   (third-party data leakage). Fixed by `false`.
4. **No security headers**: missing X-Frame-Options, X-Content-Type-Options,
   CSP, HSTS. Fixed by nginx config (production deployment).

## Verification

- 17 NEW tests passing
- 4/4 security checks pass on default config.toml
- TOML parses correctly (verified)
- pre-commit hook registered (CI gate)
- Streamlit 1.58.0 supports `corsAllowedOrigins` (since 1.30)

## Files changed summary

- W1: 1 file (+31, -2) — config.toml
- W2+W3: 3 files (+320, -0) — nginx config + validator + pre-commit
- W4: 2 files (+299, -1) — tests + main() fix
- W5: 3 files (closure, this commit)
- **Total: 9 files, NET +737 LOC**

## S79+ epic candidates

1. **P1: PoolHealthMonitor registration** (LiteLLM Gateway, FINAL_REPORT_V2 P1)
2. **P1: CircuitBreakerMiddleware restoration** (FINAL_REPORT_V2 P1)
3. **P1: docs/cookbooks/** (FINAL_REPORT_V2 P1)
4. **Per-invoke tool enforcement** (PydanticAI dispatch hook, S76 stub)
5. **Hub-based kernelspec API** (S75 stub)
6. **Auto-extend / fail-closed для leader election** (S71 W3 DONE)

## All 4 P0 items closed (FINAL_REPORT_V2 P0)

| P0 | Status | Sprint |
|---|---|---|
| **P0-A** SyntaxError (26→83 files) | ✅ CLOSED | S73 |
| **P0-B** tools whitelist в AIPolicySpec | ✅ CLOSED | S76 |
| **P0-C** AI Policy Spec DSL (ADR-0067) | ✅ CLOSED | S77 |
| **P0-D** CORS/XSRF в Streamlit | ✅ CLOSED | S78 |

All 4 P0 items from FINAL_REPORT_V2 closed. P1+ candidates backlog.
