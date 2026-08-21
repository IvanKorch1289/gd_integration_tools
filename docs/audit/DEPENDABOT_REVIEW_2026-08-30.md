# DEPENDABOT_REVIEW_2026-08-30 — Sprint 43 W2 audit

> **Method**: `gh pr list` + manual categorization.
> **Scope**: 13 OPEN dependabot PRs (verified 2026-08-30).
> **No merges performed** (out of scope per AGENTS.md `git push` deny).

## Summary

| # | PR | From → To | Age | Risk | Action |
|---|---|---|---|---|---|
| 91 | zaproxy/action-api-scan | 0.9.0 → 0.10.0 | 60d | LOW | Auto-merge candidate |
| 92 | dorny/paths-filter | 3 → 4 | 60d | LOW | Auto-merge candidate |
| 93 | actions/upload-artifact | 4 → 7 | 60d | LOW | Auto-merge candidate |
| 94 | actions/setup-python | 5 → 6 | 60d | LOW | Auto-merge candidate |
| 95 | actions/cache | 4 → 6 | 60d | LOW | Auto-merge candidate |
| 97 | mlflow | 3.13.0 → 3.14.0 | 55d | MED | Test before merge |
| 99 | patchright | 1.60.1 → 1.61.2 | 55d | MED | Test before merge |
| 120 | streamlit | 1.61.0 → 1.61.1 | 20d | LOW | Auto-merge candidate |
| 121 | aioimaplib | 1.2.0 → 2.0.1 | 20d | **HIGH** | Major version, manual review |
| 123 | sentence-transformers | 5.6.1 → 5.7.0 | 20d | LOW | Auto-merge candidate |
| 124 | nbformat | 5.10.4 → 5.11.0 | 20d | LOW | Auto-merge candidate |
| 125 | mkdocstrings | 0.30.1 → 1.0.6 | 20d | **HIGH** | Major version, manual review |
| 126 | icalendar | 6.3.2 → 7.2.2 | 20d | **HIGH** | Major version, manual review |

**Total**: 13 OPEN PRs (8 Python deps + 5 GitHub Actions).

## Recommendation: 3-phase merge

### Phase 1: 8 low-risk (auto-merge after CI pass)
- 5 GitHub Actions bumps (PRs 91-95)
- 3 patch/minor Python bumps (PRs 120, 123, 124)

**Time**: 30 min (review CI status + merge via `gh pr merge --auto`)

### Phase 2: 2 medium-risk (test before merge)
- PR 97 (mlflow 3.13→3.14): check mlflow tracking still works in test suite
- PR 99 (patchright 1.60→1.61): re-run playwright e2e tests

**Time**: 1-2h (run subset of tests on each branch)

### Phase 3: 3 high-risk (manual review + breaking change audit)
- PR 121 (aioimaplib 1→2): MAJOR version. Check email processor modules.
- PR 125 (mkdocstrings 0.30→1.0): MAJOR version. May break docs build.
- PR 126 (icalendar 6→7): MAJOR version. May break calendar DSL.

**Time**: 4-8h (read changelogs, update code if API changes)

## Why no merges performed in this sprint

Per `AGENTS.md` deny-list:
> `git push`, `make push`, `make ship`, `make ship-release` — all deny.

Dependabot merges require `gh pr merge` which is a remote mutation.
This audit documents the backlog; **merge decisions are user-only**.

## Recommended next action for user

```bash
# Phase 1: bulk-merge low-risk (5 min)
gh pr merge 91 92 93 94 95 120 123 124 --auto --squash

# Phase 2: test medium-risk on separate branches
gh pr checkout 97 && pytest tests/integration/ai -k mlflow
gh pr checkout 99 && pytest tests/e2e/

# Phase 3: manual review high-risk
gh pr view 121 --json body,files  # read breaking changes
gh pr view 125 --json body,files
gh pr view 126 --json body,files
```

## Environment note

- `gh` CLI available: YES (verified `gh pr list`)
- `gh pr merge` requires write access (user-only)
- Oldest unmerged PR: 60 days (Phase 1 PRs from 2026-07-01)
