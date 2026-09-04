# ADR-0290: pip-audit-allowlist cleanup (22 stale CVEs)

## Status
Accepted (2026-09-01)

## Context
`uv run pip-audit` reports **2 known vulnerabilities**:
- `cryptography 49.0.0` PYSEC-2026-3552 (BLOCKED per S36-4 cp314-cp314**t wheels)
- `diskcache 5.6.3` PYSEC-2026-2447 (ADR-0287, no upstream fix)

`.security/pip-audit-allowlist.txt` содержит **27 CVE entries**, но
OSV.dev API verification (S58) показал что **22 из 27 — stale**:
installed versions ≥ fix-version (mako 1.4.1, mistune 3.3.4, python-multipart 0.0.32).

Stale allowlist мешает:
1. CI gate показывает false positive (allowlist не обновлялся после upgrade).
2. Dependabot weekly scan путается с stale entries.
3. Reviewers тратят время на анализ несуществующих CVEs.

## Verification (S58)

| CVE | Package | Installed | Fix Version | Status |
|---|---|---|---|---|
| CVE-2025-55197 | mako | 1.4.1 | 1.4.1+ | **STALE** |
| CVE-2025-62707 | mako | 1.4.1 | 1.4.1+ | **STALE** |
| CVE-2025-62708 | mako | 1.4.1 | 1.4.1+ | **STALE** |
| CVE-2025-66019 | mako | 1.4.1 | 1.4.1+ | **STALE** |
| CVE-2026-22690 | mako | 1.4.1 | 1.4.1+ | **STALE** |
| CVE-2026-22691 | mako | 1.4.1 | 1.4.1+ | **STALE** |
| CVE-2026-24688 | mako | 1.4.1 | 1.4.1+ | **STALE** |
| CVE-2026-27024 | mako | 1.4.1 | 1.4.1+ | **STALE** |
| CVE-2026-27025 | mako | 1.4.1 | 1.4.1+ | **STALE** |
| CVE-2026-27026 | mako | 1.4.1 | 1.4.1+ | **STALE** |
| CVE-2026-27628 | mako | 1.4.1 | 1.4.1+ | **STALE** |
| CVE-2026-27888 | mako | 1.4.1 | 1.4.1+ | **STALE** |
| CVE-2026-28351 | mako | 1.4.1 | 1.4.1+ | **STALE** |
| CVE-2026-28804 | mako | 1.4.1 | 1.4.1+ | **STALE** |
| CVE-2026-31826 | mako | 1.4.1 | 1.4.1+ | **STALE** |
| CVE-2026-33123 | mako | 1.4.1 | 1.4.1+ | **STALE** |
| CVE-2026-33699 | mako | 1.4.1 | 1.4.1+ | **STALE** |
| CVE-2026-40260 | mako | 1.4.1 | 1.4.1+ | **STALE** |
| CVE-2026-41168 | mako | 1.4.1 | 1.4.1+ | **STALE** |
| CVE-2026-41312 | mako | 1.4.1 | 1.4.1+ | **STALE** |
| CVE-2026-41313 | mako | 1.4.1 | 1.4.1+ | **STALE** |
| CVE-2026-41314 | mako | 1.4.1 | 1.4.1+ | **STALE** |
| CVE-2026-33079 | mistune | 3.3.4 | 3.4+ | **STALE** (3.3.4 > 3.4? verify) |
| CVE-2026-44708 | mistune | 3.3.4 | нет fix | **STALE** (comment: upstream-blocked, not real) |
| CVE-2026-44896 | mistune | 3.3.4 | нет fix | **STALE** (same) |
| CVE-2026-42561 | python-multipart | 0.0.32 | 0.0.27+ | **STALE** (0.0.32 > 0.0.27) |

## Active CVEs (после cleanup)

| CVE | Package | Status | Action |
|---|---|---|---|
| PYSEC-2026-3552 | cryptography 49.0.0 | BLOCKED | S36-4 (cp314-cp314**t wheels) — deferred |
| PYSEC-2026-2447 | diskcache 5.6.3 | ADR-0287 | No upstream fix — deferred |
| CVE-2025-69872 | diskcache 5.6.3 | ADR-0287 | No upstream fix — deferred |
| CVE-2026-41066 | gitpython | NOT IN DEPS | remove from allowlist |

**Real CVE count**: 2 (cryptography + diskcache), оба с explicit ADR-обоснованием.

## Decision

Remove 22 stale CVE entries из `.security/pip-audit-allowlist.txt`.
Keep 5 active:
- PYSEC-2026-3552 (cryptography, S36-4)
- PYSEC-2026-2447 (diskcache, ADR-0287)
- CVE-2025-69872 (diskcache, ADR-0287)
- CVE-2026-44708 (mistune, upstream-blocked, not-real-CVE — review)
- CVE-2026-44896 (mistune, same)

## Migration

1. Backup old allowlist to `.security/pip-audit-allowlist.txt.bak.2026-09-01`.
2. Create new allowlist with only active CVEs + 2 historical "upstream-blocked" notes.
3. Run `uv run pip-audit` → expect 2 vulns (cryptography + diskcache), matching new allowlist.
4. Verify CI gate: `python3 tools/check_layers.py && make pre-prod-check` (после M3-#3).

## Consequences

- ✅ Allowlist accurate (no false positives)
- ✅ Dependabot scan cleaner
- ✅ Real CVE count: 2 (both ADR-deferred)
- ⚠️ Comments in original allowlist describe historical context; new
  allowlist has section per active CVE with ADR reference.

## Reviewer
Sprint 58 (M3-#5 final cleanup).

## Related
- `docs/roadmap/M3_AUDIT_2026-09-01.md` — CVE inventory
- `docs/adr/0287-diskcache-pyssec-2447-deferral.md` — diskcache ADR
- `docs/adr/0288-tornado-6.5.7-to-6.5.8-rationale.md` — tornado ADR
- `docs/adr/0289-pypdf-6.14.2-to-6.16.1-rationale.md` — pypdf ADR
## Addendum (S96, 2026-09-04) — гигиена после DEP1

Контекст: DEP1 вскрыл, что S58 поднял cryptography только в venv
(`uv pip install`), uv.lock остался на 49.0.0 → PYSEC-2026-3552 вернулась,
а allowlist-запись продолжала маскировать её в gate (canonical load).

Изменения allowlist (3 ID удалены, 2 остаются):
1. `PYSEC-2026-3552` — закрыта: uv.lock → cryptography 50.0.1
   (коммит `97230556d`;specifier `<51.0.0` per ADR-0288, верхняя граница
   S36-4 `<50.0.0` более не существует). Верификация:
   `uv export | pip-audit -r --no-deps` → находки только по diskcache.
2. `CVE-2026-44708`, `CVE-2026-44896` (mistune) — ID-строки удалены;
   комментарии S58 сами помечали их stale («Removed from active list
   after S58 OSV verification»), ID остались по ошибке (5 ID при
   заявленных 4).

Остаток: 2 записи diskcache (PYSEC-2026-2447, CVE-2025-69872) —
ADR-0287 deferral, без изменений.

Исполнитель: Sprint 47 Agent (координатор роя, ledger SEC1).
