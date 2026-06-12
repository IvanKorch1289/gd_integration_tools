# ADR-0179: S95 closure — DSL CRUD + docstring ratchet + stdlib audit + AuthGateway

**Sprint**: S95
**Wave**: W5 closure
**Дата**: 2026-06-13

## Резюме

S95 = 4 working waves + closure. Каждая волна = atomic commit + verification.
Итог: **4 atomic commits, 37 NEW tests, 0 new layer violations**.

## Волны

### W1 — DSL db_insert/upsert/delete (CRUD в DSL)

- `c23e...` feat: DSL db_insert/db_upsert/db_delete
  - dsl/engine/processors/db_crud.py: DbCrudProcessor (INSERT|UPSERT|DELETE)
    + standalone SQL builders (build_insert_sql, build_upsert_sql, build_delete_sql)
  - Identifier whitelist: [A-Za-z0-9_] (raises ValueError on injection)
  - Values = bind-params (no f-string SQL)
  - DELETE requires non-empty where (защита от accidental DELETE all)
  - UPSERT = PostgreSQL `ON CONFLICT DO UPDATE` (DO NOTHING если все cols = conflict_keys)
  - Composes DatabaseQueryProcessor (battle-tested connection pool + retry)
  - DSL builder methods: db_insert/upsert/delete в PersistenceMixin (12 methods total)
- 19 tests: SQL builders (12) + processor (5) + DSL (2)

### W2 — docstring ratchet -15 (567 → 552)

- `c5234ff0` docs: docstring ratchet -15
  - core/di/providers/http.py: 15 setter providers добавлены short docstrings
    (set_http_client_provider, set_smtp_client_provider, set_express_*,
    set_browser_client_provider, set_external_session_manager_provider, etc.)
- 3 cache.py setters оставлены в allowlist (next sprint)

### W3 — stdlib logging audit + regression guard

- `498a3e32` test: regression-блокировка для legit stdlib logging uses
  - 7 файлов retain stdlib logging (LEGITIMATE_STDLIB_FILES whitelist)
  - 9 tests: per-file marker check + count regression + core/* guard
  - Prevents accidental migration of legitimate stdlib uses
- Also: deleted orphan `core/auth/gateway.py` from S93 W3 (`git checkout
  && rm` chain failure)

### W4 — AuthGateway facade consolidation

- `c47e...` feat: core.auth.gateway facade
  - Thin re-export facade: AuthContext, AuthMethod, verify_request, require_auth
  - NEW: AuthGateway class (OOP wrapper с default_method + verify()/require())
  - Stable canonical import: extensions import from `core.auth.gateway`
  - Implementation remains in `entrypoints.api.dependencies.auth_selector`
- 9 tests: re-export identity + AuthGateway class + verify() + no-stdlib-logging

## Метрики

- **4 atomic commits** (W1: 1 + W2: 1 + W3: 1 + W4: 1)
- **37 NEW tests** (W1: 19 + W3: 9 + W4: 9; W2 ratchet без tests)
- **Layer violations**: 0 new (186 legacy)
- **Docstring ratchet**: 567 → 552 (-15 net, W2 only)
- **DSL PersistenceMixin**: 9 → 12 methods (db_insert/upsert/delete added)

## Решения (S95)

1. **DSL CRUD pattern** — SQL builder + thin processor composes
   `DatabaseQueryProcessor` (battle-tested connection pool + retry).
   Re-invented wheels avoided — composition over duplication.
2. **Identifier whitelist** — `[A-Za-z0-9_]` regex enforced for table/column
   names. Values via bind-params. No f-string SQL.
3. **DELETE guard** — пустой `where` raises ValueError. Защита от
   `DELETE FROM users` (без WHERE).
4. **Docstring ratchet** — manual edit (НЕ `--update-allowlist`).
   Sed-pattern: `def set_X_provider(Y: Any) -> None:\n    _overrides["X"] = Y`
   → + short docstring.
5. **AuthGateway facade** — thin re-export pattern. Implementation в
   `auth_selector.py` остаётся, но extensions получают stable canonical
   import path через `core.auth.gateway`. Future-proofing: если
   `auth_selector` будет split/refactored, gateway можно пере-направить.
6. **stdlib logging policy** — 7 файлов retain stdlib legitimately.
   `test_legitimate_stdlib_logging.py` enforce'ит политику через markers.

## False positives / отклонённые

- **DEEP-RESEARCH "12+ auth locations" claim** — false positive. Реально
  24 auth-related files, но 1 canonical `core.auth` module + 1 selector +
  2 middlewares + 1 DI + 4 endpoints = structured. AuthGateway facade
  теперь explicit canonical entry-point.
- **DEEP-RESEARCH "DSL missing db_insert/upsert/delete"** — CONFIRMED,
  реализовано в W1.

## S96+ candidate work

- S96: 552 → 540 docstring ratchet (-12, cache.py setters remaining + new)
- S96: DSL `cron` source / Airflow signal trigger (deferred from S92)
- S96: C28 (vault/ → docs/knowledge_vault/) — deferred from S92
- S97: DSL `from_schedule` improvements (misfire, jitter, calendar)
- S97: S99+ scratch the 9.0/10 maturity target (currently ~8.5)

## Lessons learned

- `--update-allowlist` is DANGEROUS for ratchet: scans all dirs, breaks
  baseline (+130 entries from 567). Always use manual edit.
- `MagicMock` auto-promotes to `AsyncMock` if has `__aenter__` — use
  explicit class for httpx mock (S94 W4).
- For docstring ratchet — sed-pattern for repetitive setters/getters
  is FAST: 15 docstrings in <1s via Python regex script.
- `git checkout` on untracked file FAILS without error (returns 1) —
  use `git checkout` only on tracked files; use `rm` for untracked.
