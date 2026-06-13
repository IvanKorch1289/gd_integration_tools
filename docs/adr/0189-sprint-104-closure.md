# ADR-0189: Sprint 104 closure — DSN tests + RPA DSL + Rate limit + MSSQL/MySQL/DB2

**Date:** 2026-06-13
**Status:** CLOSED
**Sprint window:** S103 closure (2026-06-13) → S104 W5 (2026-06-13).
**Wave pattern:** 5 waves = 5 atomic commits (S104) + 2 subagent outputs (S105 W1-W3) = 7 total this session.

---

## S104 W1 — D21 RPA DSL (commits 2065ea36 + 158d7099)

**Item:** DEEP-RESEARCH D21 (⚠️) — RPA DSL coverage gap (s3_get, sftp_get, sftp_put).

**Solution:**
* `src/backend/dsl/builders/infrastructure_dsl.py` — NEW DSL methods:
  - ``s3_get(key, result_property="s3_object")`` → ``S3GetProcessor``.
  - ``sftp_get(host, remote_path, username, password_from, key_file, timeout)`` → ``SftpGetProcessor``.
  - ``sftp_put(host, remote_path, body_from, ...)` → ``SftpPutProcessor``.
* 3 NEW processor classes (``S3GetProcessor``, ``SftpGetProcessor``, ``SftpPutProcessor``).
* Pattern: идентичен ``S3PutProcessor``/``ssh_exec`` (lifespan DI-фасады).

**Files:** ``infrastructure_dsl.py`` (+90 LOC).

**Out of scope:** real aioboto3/asyncssh wiring — S105 W3 (Task 3, real impl added в этой сессии).

---

## S104 W2 — §3.9 Rate limiting facade canonical (commit 8be8337e)

**Item:** DEEP-RESEARCH §3.9 (🟡) — 3 rate-limit implementations (per-domain).

**Solution:** Canonical re-export of ``unified_rate_limiter.get_rate_limiter()`` в ``core/resilience/rate_limiter_facade.py`` (аналогично S95 W4 AuthGateway + S103 W3 audit/facade pattern).

**Files:** NEW facade + 5/5 tests pass.

---

## S104 W3 — D19 DSN MSSQL/MySQL/DB2 (commits 50c9bd26 + 6820937d)

**Item:** DEEP-RESEARCH D19 (🔴 Critical) — ``_build_dsn()`` поддерживал ТОЛЬКО postgresql/oracle/sqlite. MSSQL/MySQL/DB2 → ``NotImplementedError``.

**Solution (commit 50c9bd26):**
* ``DatabaseTypeChoices`` + mssql / mysql / db2 (3 NEW values).
* ``_build_dsn()`` + 3 NEW branches:
  - mssql: ``mssql+{aioodbc|pyodbc}://...?driver=ODBC+Driver+17+for+SQL+Server``.
  - mysql: ``mysql+{aiomysql|pymysql}://``.
  - db2:   ``db2+ibm_db_sa://``.
* NEW ``tests/unit/core/config/test_dsn_mssql_mysql_db2.py`` (10 tests, 9 claimed passed but real = 7 fails).

**Fix (commit 6820937d):**
* W3 commit заявил "9/9 pass" — реально 7 fail с ValidationError "SSL только для PostgreSQL".
* Root cause: YAML loader auto-loads ``ssl_mode: "prefer"`` из ``dev.yml``; тесты не override → pydantic-валидатор падает.
* Helper ``_make_settings()`` с explicit ``ssl_mode=None`` override.
* ``model_config.extra="forbid"`` → helper передаёт только разрешённые kwargs.
* Corrupted mysql async test исправлен.
* DB2 async test добавлен (sync/async = один драйвер ``ibm_db_sa``).
* 10/10 tests pass после fix.

**Out of scope (S105+):** driver availability check (pyodbc/aioodbc optional deps).

---

## S104 W4 — Docstring ratchet -18 (commit dccb7c13)

**Item:** S102+ backlog — ratchet target -20.

**Solution:** 18 NEW docstrings в 4 файлах:
* ``infrastructure_dsl.py`` (1): SqlExecProcessor.
* ``ops/health.py`` (14): CheckStatus, HealthStatus, CheckResult, HealthReport + 3 properties, HealthCheck.add_http/tcp/db/redis/custom + run/run_one/clear_cache.
* ``utilities/admin_panel/setup_admin.py`` (1): setup_admin.
* ``workflows/worker.py`` (1): NoOpStepExecutor.execute_next.

**Allowlist:** 1642 → 1641 (net -1 line, но 18 NEW docstrings + line shifts от добавленных docstrings компенсируют).

**Validation:** 0 NEW violations. Pre-existing 4 failures в ``test_worker.py`` (test_run_worker_*) — verified на stashed state, не вызваны этим commit'ом.

---

## S104 W5 — Closure (this ADR + CHANGELOG)

**Sprint score:**

|| Item | S103 | S104 |
||------|------|------|
|| D21 RPA DSL | missing | s3_get/sftp_get/sftp_put (2 commits) |
|| §3.9 Rate limit | partial | canonical re-export (1 commit) |
|| D19 DSN | NotImpl | mssql/mysql/db2 + 10 tests (2 commits) |
|| Docstring ratchet | 1642 | **1641** (1 commit) |
|| **Overall** | **9.4** | **9.4** (no change — features were planned scope) |

**5 commits (S104):**
- `2065ea36` feat(s104-w1-d21-rpa): s3_get + sftp_get + sftp_put DSL methods
- `158d7099` fix(s104-w1-d21-rpa): add S3GetProcessor / SftpGetProcessor / SftpPutProcessor classes
- `8be8337e` feat(s104-w2-rate-limit): canonical re-export of unified_rate_limiter
- `50c9bd26` feat(s104-w3-d19-dsn): MSSQL / MySQL / DB2 DSN builder support
- `6820937d` fix(s104-w3-dsn-tests): repair 9 broken tests in test_dsn_mssql_mysql_db2
- `dccb7c13` docs(s104-w4-ratchet): docstring ratchet -18

**Cumulative S93-S104:** 12 sprints, 60+ atomic commits, 261+ NEW tests, 9 ADRs (0175-0189).

---

## Subagent outputs (S105 W1-W3) — bonus from this session

3 subagent dispatches + my own completion (Task 1, 3, 2):

### S105 W1 — D5 model move plan (commit 5d2206c0)
Subagent оставил inventory + 5 OPEN_QUESTIONS; я доделал 3 deliverable файла:
* `docs/migration/d5-models-to-core.md` — детальный план B1/B2/B3.
* `docs/adr/0188-d5-models-move-plan.md` — ADR.
* `scripts/verify_d5_migration_readiness.sh` — pre/post flight checks (12 → 0 violations, 5 tables reflected).
Pre-flight check passed: 12 model files, 5 tables, 41 linter violations baseline, facade OK.

### S105 W3 — D9 Temporal Schedule real impl (commit 9298d1c7)
Subagent timed out; я реализовал:
* `src/backend/infrastructure/scheduler/temporal_scheduler_backend.py` (NEW) — real impl через ``temporalio.client.Client``.
* Methods: ``schedule_cron`` / ``schedule_oneshot`` / ``cancel`` / ``list_jobs``.
* Lazy import temporalio (опциональная dep).
* Semantic difference documented: APScheduler = Python callable, Temporal = workflow name string.
* 22 NEW tests + 50/50 scheduler tests pass.

### S105 W2 — Audit soft-deprecation (commit 740f5e02)
Subagent обнаружил архитектурный конфликт (Path B chosen по consult):
* `tools/check_audit_deprecation.py` (NEW) — CI-runnable сканер.
* Modes: default (exit 0), ``--strict`` (exit 1 при callsites), ``--json``.
* 12 NEW tests pass.
* `docs/migration/audit-emit-deprecation.md` — guide с migration paths A/B/C/D.
* Measured: 22 files / 76 legacy callsites (subagent found 77; diff = docstring match).

---

## S105+ Backlog (after this session)

| Item | Status | Sprint target |
|------|--------|---------------|
| D5 B1 (6 Risk A models → core/domain/models/) | Plan ready | S105 W2 |
| D5 B2 (Risk B FK chain) | Plan ready | S105 W3-W5 |
| D5 B3 (Risk C cross-schema) | Plan ready | S106 W1-W2 |
| Audit migration Path A (per-domain helpers) | Recommended | S106 W1 |
| Audit pre-commit hook | Deferred | S106 W2 |
| Docstring ratchet -20/sprint | Continuous | S105+ |
| D9 full Temporal Schedule-to-Close (workflow registry + activity fallback) | Out of scope | S106+ |

**Total S105+ backlog:** 5-7 sprints, multi-wave execution.

---

## References

* DEEP-RESEARCH S92 state (2026-06-12) — original audit
* S103 closure (ADR-0187) — 5 commits, 19 NEW tests, score 9.4
* S101 closure (ADR-0185) — DEEP-RESEARCH follow-up
* S100 closure (ADR-0184) — TODO backlog = 0
* `~/.hermes/agent_workspaces/task2_audit_migration_report.md` — subagent-2 audit analysis
* All 6 S104 + 3 S105 commits listed above
