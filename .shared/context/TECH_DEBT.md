# TECH_DEBT — gd_integration_tools (last update: 03.06.2026)

Tracking для known issues, workarounds, и deferred work, который
нельзя закрыть в текущем спринте, но нужно зафиксировать для
будущих maintainers.

Формат: severity (low/medium/high) + рекомендуемый sprint/quarter для resolve.

---

## TD-005: `sibling-untracked-tests-broken` (medium, S39 W1)

**Файлы:** 19 untracked test files (см. `git status --short | grep ^??`):
- `tests/unit/dsl/engine/processors/test_audit_clickhouse.py` (4 fail, mock.patch на function-local import)
- `tests/unit/dsl/engine/test_versioning.py` (3 fail, mock.patch на function-local import)
- `tests/unit/dsl/engine/processors/test_sink_publish.py` (4 fail — syntax fixed in session 12e3f745 prep, но execution fails)
- `tests/unit/dsl/engine/processors/test_storage_ext.py` (syntax error fixed 12e3f745, но execution fails)
- `tests/unit/dsl/engine/processors/test_ml_inference.py` (syntax fixed, 5+ fail)
- `tests/unit/dsl/engine/processors/test_notify.py` (syntax fixed, fail)
- `tests/unit/entrypoints/api/v1/endpoints/test_admin_parallelism.py`
- `tests/unit/entrypoints/api/v1/endpoints/test_admin_resilience_profile.py`
- `tests/unit/entrypoints/api/v1/endpoints/test_admin_scheduler_dlq.py`
- `tests/unit/entrypoints/express/test_router.py`
- `tests/unit/entrypoints/filewatcher/test_watcher_manager.py`
- `tests/unit/entrypoints/filewatcher/test_watcher_routes.py`
- `tests/unit/entrypoints/websocket/test_ws_broadcast.py`
- `tests/unit/infrastructure/audit/test_event_log.py`
- `tests/unit/infrastructure/sinks/test_http_sink.py` (9 fail)
- `tests/unit/infrastructure/sinks/test_s3_sink.py` (1 fail)
- `tests/unit/infrastructure/sinks/test_webhook_sink.py` (7 fail)
- `tests/unit/infrastructure/sinks/test_email_sink.py`, `test_file_sink.py`, `test_grpc_sink.py`, `test_mq_sink.py`, `test_soap_sink.py`, `test_ws_sink.py` (passing but untracked)

**Проблема:** Sibling subagent'ы создали 19 test files без коммитов. Многие имеют:
1. Syntax errors (4 файла исправлены в session 12e3f745, но не закоммичены)
2. mock.patch на function-local imports (test_audit_clickhouse, test_versioning) — patches не срабатывают
3. Pre-existing test design issues (http_sink, s3_sink, webhook_sink)

**Решение (S39 W1):** Запустить `pytest tests/unit/<file> -v --tb=short` для каждого, починить по одному, или удалить + регенерировать через subagent с правильным TDD.

**Workaround:** Не блокирует S38 closure. Coverage на targeted модули уже добавлен в batch 6/7 (e575e84e + a20cb020).

---

## TD-004: `python-version-doc-drift` (low, S39+ decision)

**Файл:** multiple (20+ files: docs, .rules, AGENTS.md, UI, vault hints)

**Проблема:** Документация, hints в коде, и UI messages ссылаются на "Python 3.14+",
но V22 зафиксировал `requires-python = ">=3.13,<3.14"` (из-за pydantic-core 3.14
incompatible). Реальный масштаб — 20+ файлов, не 1 строка в AGENTS.md.

**Workaround:** S38 P3 = pin to 3.13. Не блокирует production.

**Decision needed (Ivan):** Python target = `>=3.13,<3.14` (current) vs `>=3.14,<3.15`
(v9 Вариант А, requires pydantic-core PyO3 0.25+) vs расширение окна. Отложено в S39.

**Refs:** v9 §II Python 3.14 Compatibility Audit, .hermes/plans/S38_V23_PLAN.md P3.

---

## TD-002: `pre-prod-check-coverage-timeout` (medium, S38+ workaround active)

**Файл:** `Makefile` (pre-prod-check target)

**Проблема:** `make pre-prod-check` (включает `make coverage-gate`) таймаутит
на 600s при полном прогоне. Background process тестировался 7+ минут.

**Workaround (S38):** Per-module `pytest --cov=src.backend.X.Y` (dotted path)
вместо project-wide. Каждый модуль проверяется отдельно. 0.5-2s на модуль.

**Fix needed:** Make `coverage-gate` использовать `--concurrency` или
parallel pytest (`pytest -n auto`) с per-CPU `coverage combine`.

**Refs:** T-P0.1.4 в `.hermes/plans/S38_P0_T-P0_1_4_coverage_gap.md`.

---

## TD-003: `vault-cipher-dead-code` (low, V24+ removal)

**Файлы:**
- `src/backend/core/security/vault_cipher.py` (~150 LOC)
- `src/backend/core/security/vault_cipher_sqlalchemy.py` (~75 LOC)

**Проблема:** Оба файла — взаимные imports (vault_cipher ↔ vault_cipher_sqlalchemy),
0 external usage за пределами самих себя. Канонический код — `secret_rotation.py`
(100% coverage, активно используется).

**Verify:** `grep -rln 'vault_cipher' src/ | grep -v 'vault_cipher.py\|vault_cipher_sqlalchemy.py'`
→ returns empty.

**Action plan:**
1. S38/S39: подтвердить 0 usage (automated grep test)
2. V24+: удалить оба файла + tests (`test_vault_cipher.py`, `test_vault_cipher_sqlalchemy.py`)
3. V24+: обновить TECH_DEBT entry → RESOLVED

**Tests preserved (S38):** 363 LOC в `tests/unit/core/security/test_vault_cipher{,_sqlalchemy}.py`
(522 tests pass) — committed чтобы deletion был low-risk в V24+.

**Refs:** `.shared/context/P0_noqa_audit.md` T-P0.1.13 closure (TECH_DEBT entries).

---

## Status summary

| ID | Severity | Sprint | Status | Action |
|----|----------|--------|--------|--------|
| TD-001 | low | S39+ | 🟡 deferred | Decision on Python target |
| TD-002 | medium | S38+ workaround | 🟡 partial | Per-module coverage active |
| TD-003 | low | V24+ removal | 🟡 deferred | Delete vault_cipher* files |

**No new entries added in S38 closure (52 коммита, 0 new tech debt).**

Все entries либо low (no production impact) либо имеют working workaround.
S38 не ввёл нового technical debt — только зафиксировал существующий.
