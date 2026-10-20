# Per-SHA evidence bundle — HEAD `35bf69eae` (2026-10-19)

> Closes **G-14** (per-SHA artifact bundle missing for current SHA).
> Per `deliverables/prod-readiness-review-2026-10-19/REVIEW.md` §2 row G-14.

## 1. Snapshot

| Metric | Value | Source |
|---|---|---|
| Full SHA | `35bf69eae31451f252657a8cb0673f00035424e6` | `git rev-parse HEAD` |
| Branch | `master` (4 ahead of origin/master) | `git status` |
| Working tree | dirty: 2 modified (CLAUDE.md, uv.lock) + 7 untracked deliverables/skills/test evidence | `git status` |
| File count (tracked) | **6 949** | `git ls-files \| wc -l` |
| Bundle created at | 2026-10-19T18:11:25 UTC | system clock |
| Author of new commits | Sprint 47 Agent (5 свежих коммитов) | `git log` |
| Days since Sep 28 baseline | 21 days | CURRENT report SHA `98698dd51` (2026-09-28) |

## 2. Gates re-measured at this SHA (independent of REVIEW §11)

### 2a. Startup-time gate (re-measurement of G-10)

**Command:** `uv run python tools/checks/startup_time.py` on HEAD `35bf69eae`.

```
TOTAL: 2.452s (median of 3)
SAMPLES: 2.342, 2.453, 2.452
        min=2.342s max=2.453s spread=0.111s
BASELINE: 2.400s (refreshed 2026-10-14 per .baselines/startup-time.json)
REGRESSION LIMIT: 3.120s (baseline × 1.3)
PER-MODULE MAX=3.0s, TOTAL MAX=3.0s
```

**Per-module medians** (all ≤ 3.0s):

| Module | Median | Samples |
|---|---:|---|
| `src.backend.core.config.features` | 0.546s | [0.526, 0.585, 0.546] |
| `src.backend.core.tenancy` | 0.392s | [0.389, 0.402, 0.392] |
| `src.backend.core.messaging` | 0.287s | [0.287, 0.269, 0.287] |
| `src.backend.dsl.registry.processor` | 0.388s | [0.375, 0.388, 0.416] |
| `src.backend.dsl.registry.lazy_processor` | 0.386s | [0.363, 0.386, 0.393] |
| `src.backend.services.routes.loader` | 0.416s | [0.398, 0.421, 0.416] |
| `src.backend.infrastructure.messaging.dlq` | 0.003s | [0.003, 0.003, 0.002] |

**Verdict**: **PASSED**. Median 2.452s vs regression limit 3.120s (within tolerance; ~668ms headroom).

### 2b. Drift finding: REVIEW §12 measurement does not reproduce

REVIEW.md §12 (commit `35bf69eae`) записал:
> "TOTAL: 1.472s (median of 3) — within 2.145s budget, G-10 CLOSED."

**Мой повторный замер на том же HEAD (`35bf69eae`) даёт 2.452s** — расхождение
в **+66%** от цифры в REVIEW §12. Возможные причины:

1. **Baseline drift**: `.baselines/startup-time.json` обновлён 2026-10-14 до
   2.40s (per файл, justification: "1.65s baseline от 2026-09-28 не отражает
   реальный cold-import на 3 разных машинах"). REVIEW §12 ссылается на лимит
   2.145s — этот лимит **устарел** (был при baseline 1.65s, старый лимит =
   1.65 × 1.3 = 2.145s). Текущий лимит = 3.120s.

2. **Не воспроизводимый репорт**: REVIEW §12 вставляет цифру
   `1.472s` без прямой ссылки на лог-файл (`startup_time.py --ratchet`
   или аналогичный). Возможно, была опечатка или measurement на другом
   run-state.

**Action**: при следующем round update REVIEW §12 — привести цифры к фактическому
measurement; уточнить, что бюджет 3.120s (не 2.145s) — старый лимит больше не
актуален после baseline ratchet (2026-10-14).

### 2c. Per-op auth coverage (G-9)

**Command:** `uv run pytest tests/integration/security/test_per_op_auth_inventory.py`

**Result**: **458 passed, 0 failed, 5 warnings** in 11.08s.

Coverage surface (parametrize matrix, per `_build_minimal_app`):
- auto-registered `/api/v1/auto/<action>` × 132 endpoints
- admin tree × 114 ops
- CRUD `/api/v1/*` × 166 ops (router-level guards)
- non-REST (soap, sse, cdc, webhooks) × 18 ops
- public-by-design (auth/*, /health, /ready, /metrics, /asyncapi) × 13 ops
- /api/admin, /api/auth, / (root) × 15 ops

Mechanism: для каждого non-public route — assert at least one of
`per-handler Depends` (op-level / router-level / common_dependencies) или
`AuthRequiredMiddleware` (defense-in-depth).

**Verdict**: **G-9 CLOSED** (independently re-verified on this SHA).

## 3. Top-5 immediate actions — final status

| # | Action | Status | Note |
|---|---|---|---|
| 1 | Apply G8 (21 atomic doc-fix) | ✅ closed (`9cae22f7c`) | dry-run exit 0 |
| 2 | Pymdown-extensions cap fix | ✅ already closed (Dependabot `56ecf3c3a`, 2026-10-15) | REVIEW §1/bullet-3 |
| 3 | Re-measure startup gate | ✅ closed at this SHA (§2a) | measured 2.452s, gate PASSED |
| 4 | **Per-SHA artifact bundle** | ✅ closed by THIS bundle | G-14 |
| 5 | Append Sprint 171+ achievements to CURRENT | ✅ closed (`851ebb3ad`) | 66 строк drift-section |

## 4. Verdict (post this bundle)

`УСЛОВНО НЕ ГОТОВ` → после этой bundle-сессии и ранее закрытых G-9, G-10, G-12, G-14,
G-15, G-19, G-20-B3 → остаются **открытыми**:

- G-3 (Scheduler facade fix) — 4-6 часов, MEDIUM риск
- G-5 (gRPC proto v2 regen) — 1-2 дня, LOW-MED
- G-6 (MQ live-verify) — 1 день + CI, infra-blocked
- G-7 (MCP HTTP mount live-verify) — 2-4 ч, default-OFF design
- G-8 (CI worker sizing) — 1-2 дня + SRE, MEDIUM
- G-11 (Coverage whole-tree) — 1 день + CI, infra-blocked
- G-13 (OWASP ZAP parser) — 4-6 ч, LOW
- G-16 (outdated MAJOR-chains) — 2-3 спринта, accepted risk (ADR-0302)
- G-18 (whole-tree unit re-run) — 30 min + 12 min run
- G-20 (G10 nav debt beyond B3) — Wave 1.5+ (B1/B2/B4 test migration + Wave 2-4)

Of these, only **G-18** is fully actionable locally without infra; G-3 / G-13 / G-20
are code-only.

## 5. Files in this bundle

| File | Content |
|---|---|
| `SHA.txt` | short/full SHA + recent commits |
| `SUMMARY.md` | this file |
| `git_log_10.txt` | last 10 commits on HEAD (raw `git log`) |
| `startup_time_gate.txt` | raw output of `tools/checks/startup_time.py` (re-measurement) |
| `auth_inventory_test.txt` | raw pytest output for `test_per_op_auth_inventory.py` |
| `README.md` | bundle navigation |
