# ADR-0291: cryptography upper bound lift <50.0.0 → <51.0.0

## Status
Accepted (2026-09-01, Sprint 58)

## Context
S36-4 (Round 70) hardening pinned `cryptography<50.0.0` потому что
50.0.0+ имел только `cp314-cp314**t** (free-threaded) wheels.
Проект использует regular CPython 3.14 (Py_GIL_DISABLED=0), поэтому
wheel-установка была заблокирована.

`pip-audit` сообщает PYSEC-2026-3552 (fix в 50.0.0) — этот CVE
НЕ закрыт до upgrade.

S58 (Sprint 58, Dependabot 24 CVE audit) verification:
- mako 1.4.1 installed → 22 mako CVEs already-patched.
- mistune 3.3.4 installed → 3 mistune CVEs already-patched.
- python-multipart 0.0.32 installed → CVE-2026-42561 already-patched.
- **cryptography 49.0.0 → 50.0.1**: PYSEC-2026-3552 still ACTIVE.
- diskcache 5.6.3 → PYSEC-2026-2447 (no upstream fix) — ADR-0287 deferred.

## S58 Build Verification

```bash
# Successful build from source (S58):
$ uv pip install --no-binary cryptography cryptography==50.0.1
Resolved 3 packages in 22ms
   Building cryptography==50.0.1
      Built cryptography==50.0.1
Prepared 1 package in 31.52s
Uninstalled 1 package in 24ms
Installed 1 package in 2ms
 - cryptography==49.0.0
 + cryptography==50.0.1

$ uv pip show cryptography
Name: cryptography
Version: 50.0.1
```

**Conclusion**: S36-4 hard BLOCK on cryptography 50+ больше не
обоснован. Source build успешен, wheels НЕ обязательны.

## Decision

1. Lift `pyproject.toml:30` upper bound `<50.0.0` → `<51.0.0`.
2. `cryptography>=50.0.0,<51.0.0` (новый минимальный constraint) —
   `pip-audit` PYSEC-2026-3552 fixed в 50.0.0+.
3. **CI migration (Sprint 59 follow-up)**: обновить `.github/workflows/*.yml`
   + `.gitlab/ci/*.gitlab-ci.yml` для использования
   `uv pip install --no-binary-package=cryptography ...` флаг.
4. **Production build (Sprint 60)**: Docker images должны
   pre-build cryptography wheel или использовать multi-stage build
   с rust toolchain (cryptography requires Rust для source build).

## Migration

```bash
# Local (S58 verified):
uv pip install --no-binary cryptography --upgrade-package cryptography

# CI (Sprint 59 follow-up):
uv sync --no-binary-package cryptography

# Docker (Sprint 60 follow-up):
# Dockerfile — pre-build wheel:
RUN uv pip wheel --no-binary cryptography cryptography==50.0.1 -w /wheels
RUN uv pip install --find-links /wheels --no-index ...
```

## Validation (S58)

- ✅ `uv pip install --no-binary cryptography 50.0.1` → success (31.5s build)
- ✅ `uv run pip-audit` после upgrade → 1 vuln remaining (diskcache)
- ✅ `pytest tests/unit/core/auth/` → 364/367 pass (3 pre-existing failures
  unrelated to cryptography: test_auth_facade patches old
  services.security.facade import path)
- ✅ 0 new regressions в core/auth tests (cryptography 50.0.1 backward-compat)

## Consequences

- ✅ PYSEC-2026-3552 cleared
- ✅ `pyproject.toml` upper bound lifted (S36-4 BLOCK removed)
- ⚠️ CI requires `--no-binary-package=cryptography` flag (Sprint 59 follow-up)
- ⚠️ Docker images требуют pre-build wheel strategy (Sprint 60)
- ✅ Local dev build works (S58 verified)

## Alternatives Considered

- **Use pre-built wheel from private index**: rejected (extra CI complexity)
- **Switch to `pyca/cryptography` conda-forge**: rejected (extra conda dep)
- **Patch dependency**: rejected (security anti-pattern)

## Reviewer
Sprint 58 (M3-#2 closure).

## Related
- `docs/adr/0289-pypdf-6.14.2-to-6.16.1-rationale.md` — pypdf similar pattern
- `docs/adr/0287-diskcache-pyssec-2447-deferral.md` — sibling deferred CVE
- `docs/adr/0290-pip-audit-allowlist-cleanup.md` — companion cleanup
- `.security/pip-audit-allowlist.txt` — 5 active entries (2 real CVEs)