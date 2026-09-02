# ADR-0287: diskcache PYSEC-2026-2447 deferral (no upstream fix)

## Status
Accepted (2026-09-01)

## Context
`pip-audit` (Sprint 52 M3-#1) reveals:

| Package | Version | CVE | Fix Available |
|---|---|---|---|
| diskcache | 5.6.3 | PYSEC-2026-2447 | **None** (no upstream fix released as of audit timestamp) |

`diskcache` is used in `src/backend/infrastructure/cache/disk_cache.py` (per
Sprint 17 K-OPS-2 — optional local-disk fallback when Redis unavailable).
Production default is Redis-backed CacheFacade; disk_cache is fallback-only.

## Decision
Pin `diskcache>=5.6.3,<6.0.0` (existing constraint per `pyproject.toml:144`),
document deferral, monitor upstream for fix.

When upstream releases fix (likely diskcache 6.x or patch in 5.6.x line):
1. Update `pyproject.toml` upper bound.
2. `uv lock --upgrade diskcache`.
3. `make lint-strict && make test` (especially cache invalidation paths).

## Consequences

- **Risk**: PYSEC-2026-2447 unfixed while diskcache is pinned.
- **Mitigation**: diskcache is fallback-only (Redis is primary). Production
  deployments with `cache_backend=memory` (not prod default) are exposed.
  Per `pyproject.toml:144` comment: "pinning for Dependabot visibility".
- **Detection**: Dependabot weekly scan + S52 M3-#1 baseline re-run when
  upstream releases fix.
- **Alternative considered**: replace diskcache with custom file-cache →
  DEFERRED (requires 4h+ refactor; diskcache 247 LOC is too small to be
  worth replacing for fallback-only path).

## Reviewer
Sprint 52 M3-#4 (deferral ADR).

## Related
- `docs/roadmap/M3_AUDIT_2026-09-01.md` — full audit baseline
- `docs/roadmap/PRODUCTION_READINESS.md` §M3 — dependency update scope
- `pyproject.toml:144` — existing pin with comment