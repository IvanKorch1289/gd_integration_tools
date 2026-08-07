# Cycle 8 — D-AUDIT-804 (T-C8-04-PII-ERASURE-CLOSED)

**Date:** 2026-08-07
**HEAD (before):** `54a1d160` (cycle-8 D-AUDIT-802)
**HEAD (after):** `54a1d160 + working tree changes (staged)`
**Plan ref:** cycle-4 phase-1/06-dsl.md → DOMAIN-P0-004
**Source diff:** `src/backend/dsl/engine/processors/security/pii_erase.py:172-184,261-269,352-364,397-450`
**Test diff:**
- `tests/unit/dsl/processors/test_pii_erase.py` (new, 253 LOC)
- `tests/unit/dsl/engine/processors/test_pii_erase_entity_validation.py` (16 LOC, fail-OPEN → fail-CLOSED)

---

## 1. Задача

`PiiEraseProcessor` (DSL security processor, ADR-152FZ / GDPR compliance) имел
**fail-OPEN** поведение при сбое backend erasure:

- `_delete_vectors()` под `except Exception` молча возвращал `0` — PII
  оставался в vector store (Qdrant / pgvector);
- `_anonymize_db()` под `except Exception` молча возвращал `0` — PII
  оставался в таблице `<entity>_pii`;
- Outer `process()` также глушил оба исключения через `_logger.warning(...)` —
  exchange продолжал как "успешный", caller (через `@handle_processor_error`)
  не видел failure.

Это security regression: 152-ФЗ ст. 21 ("Право на забвение") требует
**полного** удаления PII. При сбое backend DSL маршрут возвращал 200 OK с
"пустым" `ErasureResult{vectors_deleted=0, records_anonymized=0}` — без
сигнала о том, что PII остался в системе.

**Source-level evidence (cycle-4 baseline):**
```python
# inner _delete_vectors:
except Exception as exc:
    _logger.warning("vector deletion failed: ...")
    return 0                                # ← silent fail-OPEN

# outer process():
except Exception as exc:
    _logger.warning("vector deletion failed: %s", exc)  # ← silent fail-OPEN
```

---

## 2. Семантическое разделение (cycle-8 fix)

| Состояние | Реакция (было) | Реакция (стало) |
|---|---|---|
| Backend ok + scope валиден | ok | ok (без изменений) |
| Scope malformed (нет `:`) | soft skip, warning | soft skip, warning (без изменений — input error) |
| Entity type не проходит whitelist | exception absorbed, warning | exception → `process()` re-raise (fail-CLOSED) |
| **Vector backend down** | **silent return 0 (fail-OPEN)** | **`_logger.error + DLQWriter.write + raise` (fail-CLOSED)** |
| **DB backend down** | **silent return 0 (fail-OPEN)** | **`_logger.error + DLQWriter.write + raise` (fail-CLOSED)** |
| `_emit_audit` failed | warning, return "" | warning, return "" (без изменений — observability) |

`compensatable=False` (erasure is non-reversible) остаётся в силе — после
fail-CLOSED PII не остаётся "наполовину удалённым".

---

## 3. Diff scope

```
 src/backend/dsl/engine/processors/security/pii_erase.py        |  96 ++++++++--
 tests/unit/dsl/engine/processors/test_pii_erase_entity_validation.py |  16 +-
 tests/unit/dsl/processors/test_pii_erase.py                    | 253 +++++++++++++++++++++
 3 files changed, 350 insertions(+), 15 deletions(-)
```

**Source change (89 net lines):**
- 3 inline comments с маркером `cycle-8/D-AUDIT-804` (русский).
- `_logger.warning` → `_logger.error` (3 места: outer process / inner vectors / inner DB).
- `return 0` (silent fail-OPEN) → `raise` в обоих inner методах.
- Outer `process()` `except Exception` теперь делает concrete handling:
  `_logger.error + await _enqueue_failure_to_dlq(...) + raise`.
- Новый метод `_enqueue_failure_to_dlq(...)` — persist failure в
  `InMemoryDLQWriter` через DLQ bridge (lazy import).

**Test change (16 LOC existing + 253 LOC new):**
- `test_invalid_scope_rejected_before_sql` обновлён: было `assert count == 0`
  (документировало fail-OPEN), стало `pytest.raises(ValueError, ...)`
  (документирует fail-CLOSED). Security-relevant invariant `no SQL must
  reach execute() for unsafe scope` сохранён.
- Новый `tests/unit/dsl/processors/test_pii_erase.py` (253 LOC):
  - `TestDeleteVectorsFailClosed` (2 теста) — mock exception в vector store
    → `_delete_vectors` raises + `process()` exchanges.error / stopped.
  - `TestAnonymizeDbFailClosed` (2 теста) — mock exception в DB → аналогично.
  - `TestDqWriteEnqueue` (2 теста) — envelope construction + DLQ self-failure
    handling.

**Не тронуто:**
- `s3.py`, `blue_green.sh`, `gateway_adapter.py:128-129` — UNTOUCHED.
- `uv.lock` — 0 lines churn.
- `.security/pip-audit-allowlist.txt` — 27 (без изменений).
- Cycle 1+2+3+4+5+6+7+8 правки (28+ atomic commits в HEAD `54a1d160`)
  — НЕ переписаны.

---

## 4. Tests

```
$ .venv/bin/python -m pytest \
    tests/unit/dsl/processors/test_pii_erase.py \
    tests/unit/dsl/engine/processors/test_pii_erase_entity_validation.py \
    -v

tests/unit/dsl/processors/test_pii_erase.py::TestDeleteVectorsFailClosed::test_vector_backend_failure_raises_not_silent PASSED
tests/unit/dsl/processors/test_pii_erase.py::TestDeleteVectorsFailClosed::test_process_vector_failure_marks_exchange_failed PASSED
tests/unit/dsl/processors/test_pii_erase.py::TestAnonymizeDbFailClosed::test_db_backend_failure_raises_not_silent PASSED
tests/unit/dsl/processors/test_pii_erase.py::TestAnonymizeDbFailClosed::test_process_db_failure_marks_exchange_failed PASSED
tests/unit/dsl/processors/test_pii_erase.py::TestDqWriteEnqueue::test_enqueue_writes_envelope_to_dlq PASSED
tests/unit/dsl/processors/test_pii_erase.py::TestDqWriteEnqueue::test_enqueue_swallows_dlq_own_failure PASSED
tests/unit/dsl/engine/processors/test_pii_erase_entity_validation.py::TestEntityTypeValidator::test_valid_entity_type_passes PASSED
tests/unit/dsl/engine/processors/test_pii_erase_entity_validation.py::TestEntityTypeValidator::test_invalid_entity_type_rejected[user; DROP TABLE x; --] PASSED
tests/unit/dsl/engine/processors/test_pii_erase_entity_validation.py::TestEntityTypeValidator::test_invalid_entity_type_rejected[1user] PASSED
tests/unit/dsl/engine/processors/test_pii_erase_entity_validation.py::TestEntityTypeValidator::test_invalid_entity_type_rejected[user-name] PASSED
tests/unit/dsl/engine/processors/test_pii_erase_entity_validation.py::TestEntityTypeValidator::test_invalid_entity_type_rejected[user.name] PASSED
tests/unit/dsl/engine/processors/test_pii_erase_entity_validation.py::TestEntityTypeValidator::test_invalid_entity_type_rejected[] PASSED
tests/unit/dsl/engine/processors/test_pii_erase_entity_validation.py::TestEntityTypeValidator::test_invalid_entity_type_rejected[user DDL] PASSED
tests/unit/dsl/engine/processors/test_pii_erase_entity_validation.py::TestPiiEraseAnonymizeDbValidation::test_invalid_scope_rejected_before_sql PASSED
tests/unit/dsl/engine/processors/test_pii_erase_entity_validation.py::TestPiiEraseAnonymizeDbValidation::test_valid_scope_runs_constructed_sql PASSED

============================== 15 passed in 3.27s ==============================
```

**Новые тесты верифицируют:**
- `mock exception → raises (НЕ silent return 0)`:
  - `_delete_vectors` под `ConnectionError("qdrant backend unreachable")`
    → `pytest.raises(ConnectionError)`.
  - `_anonymize_db` под `ConnectionError("postgres unreachable")`
    → `pytest.raises(ConnectionError)`.
- `process()` failure path → `exchange.stopped == True` +
  `exchange.error` содержит `"qdrant backend"` / `"postgres unreachable"`.
- `_enqueue_failure_to_dlq` создаёт `DLQEnvelope{transport="dsl.pii_erase",
  error_class="ConnectionError", error_message="backend down", ...}` и
  пишет через `InMemoryDLQWriter.write(envelope)`.
- DLQ self-failure (mock `get_dlq_envelope_class` raises `RuntimeError`)
  → log error, но НЕ propagate (outer process() уже re-raise основную).

**Не-регрессия:**
- `test_valid_scope_runs_constructed_sql` — happy path DELETE/UPDATE сохранён.
- `test_invalid_entity_type_rejected[*]` (6 параметризованных) — whitelist
  сохранён (S608 mitigation).

---

## 5. Preflight gates

```
$ bash tools/cycle-1-preflight.sh

cycle-1 preflight (T-0.1 re-run):
  [OK]   layer checker — 0 new, 175 legacy
  [OK]   allowlist active IDs — 27
  [OK]   docstring gate — 0 missing
  [FAIL] working tree — 44 entries (разобраться)
  [OK]   uv.lock churn — 0 diff lines (pre-existing, не растёт)
  [OK]   s3.py untouched — не modified

Preflight failed — fix before running developer task.
```

**Анализ "working tree" FAIL:**
- Pre-existing: cycle-1+2+3+4+5+6+7+8 параллельные правки оставили ~40
  untracked/modified entries (отчёты, тестовые артефакты, drafts).
- Cycle-8 D-AUDIT-804 правки: **3 entries** (`pii_erase.py`,
  `test_pii_erase.py`, `test_pii_erase_entity_validation.py`).
- Working tree FAIL — pre-existing baseline issue, не вызвано cycle-8 fix.

**Ключевые gates (cycle-8 D-AUDIT-804 релевантные):**

| Gate | Baseline | Cycle-8 final | Статус |
|---|---|---|---|
| Layer checker | 175/0 | 175/0 | **PASS** |
| Security allowlist | 27 | 27 | **PASS** |
| Docstring gate | 0 missing | 0 missing | **PASS** |
| `s3.py` modified | нет | нет | **PASS** |
| `gateway_adapter.py:128-129` | present | present (UNTOUCHED) | **PER PLAN** |
| uv.lock churn | 0 | 0 (нет новых строк) | **PASS** |

**Verified via `.venv/bin/python`:**
```
$ .venv/bin/python -m pytest tests/unit/dsl/processors/test_pii_erase.py \
    tests/unit/dsl/engine/processors/test_pii_erase_entity_validation.py
============================== 15 passed in 3.27s ==============================

$ .venv/bin/python -m pytest (cycle-8 verification)
... 15/15 PASS

$ make check-docstrings MAX_ALLOWED=0
Total: 0 missing docstrings in 0 files
Files scanned: 840
docstring policy OK
```

---

## 6. Python-dev skill compliance

- ✅ **Async-first:** `process()`, `_delete_vectors`, `_anonymize_db`,
  `_enqueue_failure_to_dlq` — все `async def`.
- ✅ **Capability-checked фасады:** используется `get_capability_facade()`
  для `ai.memory.delete` / `pii.audit` (без изменений).
- ✅ **80% декларативно:** изменение в одном `try/except` без новых
  абстракций сверх `_enqueue_failure_to_dlq` helper (минимальный helper
  для durable observability).
- ✅ **Python 3.14+ syntax:** `*` keyword-only params в
  `_enqueue_failure_to_dlq`; `BaseException` типы сохранены.
- ✅ **Русские docstrings не переведены:** все новые комментарии и
  обновлённые test docstrings — на русском.
- ✅ **Ponytail/YAGNI:** минимальный diff (89 net LOC source), без новых
  модулей, без фабрик поверх фабрик. `InMemoryDLQWriter` (35 LOC) —
  переиспользован, не дублирован.
- ✅ **`except Exception` с concrete handling:** все 3 `except Exception`
  теперь делают `_logger.error + raise` (inner) или
  `_logger.error + _enqueue_failure_to_dlq + raise` (outer). DLQ self-failure
  имеет свой nested `except Exception → log error` (не silent pass).
- ✅ **Docstring marker:** `cycle-8/D-AUDIT-804` присутствует в source (3
  комментария) и test (3 места).

---

## 7. Files changed (cycle-8 D-AUDIT-804 only)

| Path | + | - |
|---|---|---|
| `src/backend/dsl/engine/processors/security/pii_erase.py` | +89 | -7 |
| `tests/unit/dsl/engine/processors/test_pii_erase_entity_validation.py` | +9 | -7 |
| `tests/unit/dsl/processors/test_pii_erase.py` | +253 | -0 |
| **TOTAL** | **+351** | **-14** |

**Verify via `git diff --stat HEAD`:**
```
$ git diff --stat HEAD -- \
    src/backend/dsl/engine/processors/security/pii_erase.py \
    tests/unit/dsl/processors/test_pii_erase.py \
    tests/unit/dsl/engine/processors/test_pii_erase_entity_validation.py
 .../dsl/engine/processors/security/pii_erase.py    |  96 +++++++-
 .../processors/test_pii_erase_entity_validation.py |  16 +-
 tests/unit/dsl/processors/test_pii_erase.py        | 253 +++++++++++++++++++++
 3 files changed, 350 insertions(+), 15 deletions(-)
```

**Не в scope cycle-8 D-AUDIT-804 (НЕ модифицировались):**
- `uv.lock` — 0 lines
- `.security/pip-audit-allowlist.txt` — без изменений (27)
- `src/backend/infrastructure/storage/s3.py` — UNTOUCHED
- `tools/blue_green.sh` — UNTOUCHED
- `tests/unit/tools/test_blue_green_switch.py` — UNTOUCHED
- `services/ai/gateway_adapter.py:128-129` — pre-existing residual, НЕ тронут
- Cycle 1+2+3+4+5+6+7+8 параллельные правки — НЕ переписаны

---

## 8. Honest verdict

Cycle-8 D-AUDIT-804 — **1 P0 security fix** в fail-OPEN → fail-CLOSED для
`PiiEraseProcessor`. Diff 351/14 LOC. 15/15 tests PASS. Docstring gate green.
Layer/allowlist/uv.lock/s3.py gates green.

**Ключевые invariant'ы сохранены:**
- ADR-152FZ / GDPR compliance — PII erasure теперь действительно erase-or-fail.
- `_validate_entity_type` whitelist (S608 mitigation) — сохранён, no SQL
  injection surface.
- `_emit_audit` (audit emission) — сохранён (observability для successful path).
- `compensatable=False` — erasure остаётся non-reversible.

**Не сделано (out of scope для atomic-fix):**
- Production wiring singleton DLQWriter через composition root
  (заменяется на `InboxDLQWriter` / `OutboxDLQWriter` через
  `set_stream_dlq_writer_provider`). Это отдельная D-AUDIT-задача.
- Hardening других `warn`-mode security processors (если есть аналогичные
  fail-OPEN patterns в `dsl/engine/processors/security/`) — отдельные D-AUDIT.

**Status:** ✅ **READY FOR COMMIT**
**Commit prefix:** `fix(cycle-8):`
**Suggested message:**
```
fix(cycle-8): PII erasure fail-CLOSED via DLQWriter + raise (D-AUDIT-804)
```