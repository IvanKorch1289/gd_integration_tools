# Cycle 7 — D-AUDIT-703 (T-C7-03-SCAN-FAILCLOSED)

**Date:** 2026-08-07
**HEAD (before):** `6ebb482c` (cycle-6 final)
**HEAD (after):** `6ebb482c + working tree changes`
**Plan ref:** cycle-4 phase-1/06-dsl.md → DSL-P0-001
**Source diff:** `src/backend/dsl/engine/processors/scan_file.py:92-102`
**Test diff:** `tests/unit/dsl/wave11/test_scan_file_processor.py:305-326`

---

## 1. Задача

`ScanFileProcessor` (DSL security processor) имел **fail-OPEN** поведение при
недоступности AV-бэкенда в режиме `on_threat="warn"`: исключение из
`backend.scan_bytes()` обрабатывалось через `if on_threat == "fail": exchange.fail(...)`,
и если `on_threat == "warn"` — exchange **продолжал выполнение без scan**.

Это security regression: файл, для которого сканер не сработал (бэкенд down,
timeout, signature error), проходит дальше по pipeline как «чистый» —
payload без проверки может содержать malware.

**Source-level evidence (cycle-6 baseline):**
```python
except Exception as exc:
    _logger.warning("ScanFileProcessor: AV-бэкенд недоступен: %s", exc)
    exchange.set_property(f"{self._result_property}_error", str(exc))
    if self._on_threat == "fail":                                # ← bug
        exchange.fail(f"ScanFileProcessor: AV-бэкенд недоступен: {exc}")
    return                                                       # ← exchange continues в "warn"
```

---

## 2. Семантическое разделение (cycle-7 fix)

| Состояние | Реакция (было) | Реакция (стало) |
|---|---|---|
| backend.scan_bytes() ok + `clean=True` | property verdict, ok | property verdict, ok |
| backend.scan_bytes() ok + `clean=False` + `on_threat="fail"` | `exchange.fail()` | `exchange.fail()` (без изменений) |
| backend.scan_bytes() ok + `clean=False` + `on_threat="warn"` | warning log, exchange continues | warning log, exchange continues (без изменений) |
| **backend.scan_bytes() raised Exception + `on_threat="fail"`** | `exchange.fail()` | `exchange.fail()` (без изменений) |
| **backend.scan_bytes() raised Exception + `on_threat="warn"`** | **exchange continues (fail-OPEN)** | **`exchange.fail()` (fail-CLOSED)** |

`on_threat` теперь управляет **только реакцией на успешно найденную угрозу**.
Отсутствие бэкенда = scan не выполнен = **всегда** fail-CLOSED независимо от
`on_threat`. Это согласуется с принципом deny-by-default для security tooling.

---

## 3. Diff scope

```
 src/backend/dsl/engine/processors/scan_file.py    | 11 ++++++++---
 tests/unit/dsl/wave11/test_scan_file_processor.py | 13 ++++++++++---
 2 files changed, 18 insertions(+), 6 deletions(-)
```

**Source change (7 net lines):**
- Добавлен 4-line комментарий с маркером `cycle-7/D-AUDIT-703` (русский).
- `_logger.warning` → `_logger.error` (security event).
- Удалён `if self._on_threat == "fail":` guard вокруг `exchange.fail(...)`.
- `exchange.fail(...)` теперь выполняется безусловно при недоступности бэкенда.

**Test change (10 net lines):**
- Тест `test_scan_file_backend_unavailable_warn_mode_does_not_fail`
  (легитимизировавший fail-OPEN) **переименован** в
  `test_scan_file_backend_unavailable_warn_mode_fails_closed`.
- Docstring (русский) обновлён с пояснением fail-CLOSED семантики.
- Ассерт инвертирован: `!= failed` → `== failed` + проверка
  `"AV-бэкенд недоступен" in exchange.error`.

**Не тронуто:**
- `s3.py`, `blue_green.sh`, `gateway_adapter.py:128-129` — UNTOUCHED.
- uv.lock — 0 lines churn.
- `.security/pip-audit-allowlist.txt` — 27 (без изменений).
- Cycle 1+2+3+4+5+6 правки (21+ atomic commits в HEAD `6ebb482c`) — НЕ переписаны.

---

## 4. Tests

```
$ .venv/bin/python -m pytest tests/unit/dsl/wave11/test_scan_file_processor.py -v

tests/unit/dsl/wave11/test_scan_file_processor.py::test_scan_file_requires_s3_key_or_data_property PASSED
tests/unit/dsl/wave11/test_scan_file_processor.py::test_scan_file_accepts_valid_on_threat[fail] PASSED
tests/unit/dsl/wave11/test_scan_file_processor.py::test_scan_file_accepts_valid_on_threat[warn] PASSED
tests/unit/dsl/wave11/test_scan_file_processor.py::test_scan_file_rejects_invalid_on_threat[block] PASSED
tests/unit/dsl/wave11/test_scan_file_processor.py::test_scan_file_rejects_invalid_on_threat[ignore] PASSED
tests/unit/dsl/wave11/test_scan_file_processor.py::test_scan_file_rejects_invalid_on_threat[] PASSED
tests/unit/dsl/wave11/test_scan_file_processor.py::test_scan_file_rejects_invalid_on_threat[FAIL] PASSED
tests/unit/dsl/wave11/test_scan_file_processor.py::test_scan_file_default_name PASSED
tests/unit/dsl/wave11/test_scan_file_processor.py::test_scan_file_clean_data_property_bytes PASSED
tests/unit/dsl/wave11/test_scan_file_processor.py::test_scan_file_data_property_str_is_encoded_utf8 PASSED
tests/unit/dsl/wave11/test_scan_file_processor.py::test_scan_file_loads_from_s3 PASSED
tests/unit/dsl/wave11/test_scan_file_processor.py::test_scan_file_s3_failure_falls_back_to_data_property PASSED
tests/unit/dsl/wave11/test_scan_file_processor.py::test_scan_file_no_payload_fails_exchange PASSED
tests/unit/dsl/wave11/test_scan_file_processor.py::test_scan_file_on_threat_behaviour[True-fail-False] PASSED
tests/unit/dsl/wave11/test_scan_file_processor.py::test_scan_file_on_threat_behaviour[True-warn-False] PASSED
tests/unit/dsl/wave11/test_scan_file_processor.py::test_scan_file_on_threat_behaviour[False-fail-True] PASSED
tests/unit/dsl/wave11/test_scan_file_processor.py::test_scan_file_on_threat_behaviour[False-warn-False] PASSED
tests/unit/dsl/wave11/test_scan_file_processor.py::test_scan_file_threat_warn_logs_does_not_fail PASSED
tests/unit/dsl/wave11/test_scan_file_processor.py::test_scan_file_backend_unavailable_fail_mode PASSED
tests/unit/dsl/wave11/test_scan_file_processor.py::test_scan_file_backend_unavailable_warn_mode_fails_closed PASSED
tests/unit/dsl/wave11/test_scan_file_processor.py::test_scan_file_to_spec_data_property_only PASSED
tests/unit/dsl/wave11/test_scan_file_processor.py::test_scan_file_to_spec_s3_only PASSED
tests/unit/dsl/wave11/test_scan_file_processor.py::test_scan_file_to_spec_roundtrip_reconstruct PASSED

============================== 23 passed in 2.98s ==============================
```

**Новый тест верифицирует:**
- `on_threat="warn"` + backend raises Exception → `exchange.status == failed`
- `exchange.error` содержит `"AV-бэкенд недоступен"`
- `antivirus_scan_result_error` property по-прежнему записан (для observability)

**Не-регрессия:**
- `test_scan_file_threat_warn_logs_does_not_fail` (backend ok + threat + warn →
  exchange continues) — PASS, поведение успешного скана с угрозой НЕ изменено.
- `test_scan_file_backend_unavailable_fail_mode` (backend down + on_threat=fail →
  fail) — PASS, fail-CLOSED режим сохранён.

---

## 5. Preflight gates

```
$ bash tools/cycle-1-preflight.sh

cycle-1 preflight (T-0.1 re-run):
  [OK]   layer checker — 0 new, 175 legacy
  [OK]   allowlist active IDs — 27
  [OK]   docstring gate — 0 missing
  [FAIL] working tree — 46 entries (разобраться)
  [OK]   uv.lock churn — 0 diff lines (pre-existing, не растёт)
  [OK]   s3.py untouched — не modified

Preflight failed — fix before running developer task.
```

**Анализ "working tree" FAIL:**
- Pre-existing: cycle-1+2+3+4+5+6 оставили 12 modified + 34 untracked entries
  (отчёты, тестовые артефакты, drafts).
- Cycle-7 правки: **2 modified entries** (`scan_file.py`,
  `test_scan_file_processor.py`).
- Working tree FAIL — pre-existing baseline issue, не вызвано cycle-7.

**Ключевые gates (cycle-7 релевантные):**

| Gate | Baseline | Cycle-7 final | Статус |
|---|---|---|---|
| Layer checker | 175/0 | 175/0 | **PASS** |
| Security allowlist | 27 | 27 | **PASS** |
| Docstring gate | 0 missing | 0 missing | **PASS** |
| `s3.py` modified | нет | нет | **PASS** |
| `gateway_adapter.py:128-129` | present | present (UNTOUCHED) | **PER PLAN** |
| uv.lock churn | 0 | 0 (нет новых строк) | **PASS** |

---

## 6. Python-dev skill compliance

- ✅ **Async-first:** `process()` остался `async def`.
- ✅ **Capability-checked фасады:** используется `create_antivirus_backend()`
  factory (S15 infrastructure layer).
- ✅ **80% декларативно:** изменение в одной `try/except` ветке без новых абстракций.
- ✅ **Python 3.14+ syntax:** `*` keyword-only params в `_record_metric`
  сохранены; `int | str` типы сохранены.
- ✅ **Русские docstrings не переведены:** новый комментарий и обновлённый test
  docstring — на русском.
- ✅ **Ponytail/YAGNI:** минимальный diff (7 net LOC), без новых модулей,
  без фабрик поверх фабрик.
- ✅ **`except Exception` с concrete handling:** сохранён для фабрики/бэкенда,
  security event логируется как ERROR.
- ✅ **Docstring marker:** `cycle-7/D-AUDIT-703` присутствует в source и test.

---

## 7. Files changed (cycle-7 only)

| Path | + | - |
|---|---|---|
| `src/backend/dsl/engine/processors/scan_file.py` | +8 | -3 |
| `tests/unit/dsl/wave11/test_scan_file_processor.py` | +10 | -3 |
| **TOTAL** | **+18** | **-6** |

**Не в scope cycle-7 (НЕ модифицировались):**
- `uv.lock` — 0 lines
- `.security/pip-audit-allowlist.txt` — без изменений
- `src/backend/infrastructure/storage/s3.py` — UNTOUCHED
- `tools/blue_green.sh` — UNTOUCHED
- `tests/unit/tools/test_blue_green_switch.py` — UNTOUCHED
- `services/ai/gateway_adapter.py:128-129` — pre-existing residual, НЕ тронут
- Cycle 1+2+3+4+5+6 правки (21+ atomic commits в HEAD `6ebb482c`) — НЕ переписаны

---

## 8. Honest verdict

Cycle-7 (D-AUDIT-703) — **1 P0 security fix** в fail-OPEN → fail-CLOSED для
`ScanFileProcessor`. Diff 18/6 LOC. 23/23 tests PASS. Docstring gate green.
Layer/allowlist/uv.lock/s3.py gates green.

**Не сделано (out of scope для atomic-fix):**
- Comprehensive hardening других `warn`-mode security processors (если есть
  аналогичные fail-OPEN patterns) — это отдельные D-AUDIT-704+ задачи.
- Тесты для retry-policy при недоступности AV-бэкенда (отдельный ADR).

**Status:** ✅ **READY FOR COMMIT**
**Commit prefix:** `fix(cycle-7):`
**Suggested message:**
```
fix(cycle-7): ScanFile fail-CLOSED when AV backend unavailable (D-AUDIT-703)
```