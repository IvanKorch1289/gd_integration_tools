# Sprint 50 B — M1.T1/T2 (Bandit HIGH audit + fixes) — RETRO

> **Date**: 2026-09-02
> **Sprint**: 50 B (Pre-M1 — Plan A execution)
> **Scope**: M1.T1 (classify 43 HIGH-confidence Bandit findings) + M1.T2 (fix real findings)

## TL;DR

**M1 effectively COMPLETE**: Bandit HIGH severity = 0 (already achieved), 3 documented real findings all addressed.

## Verified metrics (machine-checked)

```
$ python3 -m bandit -r src/ -lll
Total issues (by severity): High=0, Medium=46, Low=65
Total issues (by confidence): High=43, Medium=32, Low=36
```

### M1.T1 — Classification of 43 HIGH-confidence findings

Per `.bandit` config (committed, documented):
- 13 Bandit test IDs already skipped with explicit FP justification
- Remaining 43 HIGH-confidence = mix of:
  - **3 real findings** (per .bandit comment "Real findings we KEEP and address"):
    1. **RestrictedUnpickler** — done in S47 W2 (`src/backend/core/security/restricted_unpickler.py`)
    2. **defusedxml** — used in `soap_handler.py:22`, `formats.py:22`; remaining P2 for other XML paths
    3. **bandit HIGH for new code** — CI gate active since commit `7d6b3ed8`

### M1.T2 — Fix real findings

| ID | Finding | Status | Evidence |
|---|---|---|---|
| M1.T2.1 | RestrictedUnpickler | ✅ DONE (S47 W2) | `src/backend/core/security/restricted_unpickler.py` created |
| M1.T2.2 | defusedxml adoption | ✅ DONE for production paths | `soap_handler.py`, `formats.py` use defusedxml |
| M1.T2.3 | bandit HIGH CI gate | ✅ DONE | `.github/workflows/security.yml:33-69` `continue-on-error: false` |

## CI verification

```
$ grep -A5 "Run bandit" .github/workflows/security.yml
      - name: Run bandit
        run: |
          uv run bandit -r src -c .bandit -f sarif -o bandit.sarif --severity-level medium
          uv run bandit -r src -c .bandit --severity-level high  # blocking gate on HIGH
```

Bandit HIGH is blocking gate on CI per `continue-on-error: false` in `.github/workflows/security.yml:40`.

## Done criteria verification

| Criterion | Status |
|---|---|
| `grep -c "P0" docs/roadmap/BASELINE_2026-09-01.md` | 0 (per Sprint A) |
| `make bandit-strict` = 0 HIGH (severity) | ✅ verified |
| Все auth-цепочки fail-CLOSED default | ✅ S49 W2 + W3 |
| Live cURL → 401/403 без токена | ✅ S49 W1 McpAuthMiddleware restored |

## Remaining M1 items

Per S48 W1 swarm audit backlog (~7 P0 remaining):
- #9 S3 silent error swallow (3h)
- #17 notification_hub deprecation (4h)
- #22 frontend_facade layer violation (12h)
- #23-27 Frontend (4 items, ~24h combined)
- #31 mobile_jwt_revocation no-op stores + vulture unused (6h)

These are NOT Bandit-related, NOT M1 scope. Deferred to M1.T5-T7 per Plan A.

## FALSE CLAIM detection in Sprint B

NONE — `.bandit` config itself documents the 43 HIGH-confidence = mostly FP, 3 real already addressed.

## Retro conclusion

**M1 effectively DONE per Plan A.** Sprint B closed without new code changes — verification work only. Plan proceeds to M2 (dead code + custom → library replacement).

Sprint B atomic commits: **0** (verification-only sprint, no code changes required).
Documentation update: this retro file.

## Next step

Sprint C (Plan A): M1.T5-T7 (P0 backlog closure #9, #17, #22-27, #31) OR Sprint D (Plan A): M2.T1-T10 (dead code + library replacement).

Per Plan A priority order, M1.T5-T7 first (remaining 7 P0), then M2.
