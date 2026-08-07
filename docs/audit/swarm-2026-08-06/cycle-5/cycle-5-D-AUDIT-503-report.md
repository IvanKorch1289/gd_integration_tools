# Cycle 5 — D-AUDIT-503 — OSINT fail-CLOSED (LLMUnavailableError + InsufficientDataError)

> **Дата:** 2026-08-07
> **HEAD:** `e5dcf18c` + локальные правки 2 файлов (OSINT workflow + tests)
> **Domain:** Business Logic — `extensions/osint_agent/`
> **Mode:** minimal-edit, additive only (fail-CLOSED guards + tests)
> **Reference:** `docs/audit/swarm-2026-08-06/cycle-4/phase-1/10-business-logic.md` findings `BL-P0-001` + `BL-P0-002`
> **Plan ref:** cycle-4 phase-1/10-business-logic.md

---

## 1. TL;DR

| Метрика | Значение |
|---|---|
| Status | **✅ DONE — fail-CLOSED guards applied + 8 new tests PASS** |
| Findings resolved | `business-logic:BL-P0-001` + `business-logic:BL-P0-002` |
| Diff stat (cycle-5 only) | **2 files changed, 229 insertions(+), 2 deletions(-)** |
| Files modified | `extensions/osint_agent/functions/osint_workflow.py`, `extensions/osint_agent/tests/test_osint_workflow.py` |
| Tests added | **8 (4 helper + 4 run_osint scenarios)** |
| Tests passing (OSINT) | **26 passed, 2 failed** (pre-existing failures, NOT in scope — `test_valid_12_digit_inn` = BL-P2-002 test data bug; `test_none_inn` = BL-P1-003 validate_inn None) |
| Tests passing (extensions/) | **91 passed, 3 failed** (3 pre-existing failures, none from this work) |
| Docstring gate | **0 missing** (840 files scanned) |
| Layer check | **0 new** (175/0 baseline preserved) |
| Forbidden files | **untouched** (uv.lock, .security/pip-audit-allowlist.txt, s3.py, blue_green.sh, test_blue_green_switch.py) |
| Pre-existing residuals | не трогали (`gateway_adapter.py:128-129`, `temporal_backend.py` — pre-existing modifications from cycles 1+2+3) |

---

## 2. Scope / что реально сделано

### 2.1 BL-P0-001 fix: LLM failure → LLMUnavailableError (no template echo)

**Path:** `extensions/osint_agent/functions/osint_workflow.py:307-334` (до правки)

**До:**

```python
try:
    gateway = get_litellm_gateway()
    response = await gateway.acompletion(...)
    raw_text = response.get("choices", [{}])[0].get("message", {}).get("content", "")
except Exception:
    raw_text = prompt   # ← FAIL-OPEN: echo prompt template as report
```

**После:**

```python
try:
    gateway = get_litellm_gateway()
    response = await gateway.acompletion(...)
    raw_text = response.get("choices", [{}])[0].get("message", {}).get("content", "")
except Exception as exc:
    logger.error("osint_llm_unavailable", extra={"inn": inn, "error": str(exc)})
    raise LLMUnavailableError(f"LLM unavailable for INN {inn!r}: {exc}") from exc
```

**Domain exception** (cycle-5/D-AUDIT-503):

```python
class LLMUnavailableError(Exception):
    """LLM gateway недоступен — fail-CLOSED, не возвращаем prompt template."""
```

### 2.2 BL-P0-002 fix: empty search results → InsufficientDataError (no LLM call)

**Path:** `extensions/osint_agent/functions/osint_workflow.py:307-313` (до правки)

**До:**

```python
try:
    results_general = await _search_multi_provider(queries["general"])
    results_courts = await _search_multi_provider(queries["courts"])
    results_negative = await _search_multi_provider(queries["negative"])
except Exception:
    results_general = {"perplexity": None, "tavily": None, "scraped": []}
    results_courts = {"perplexity": None, "tavily": None, "scraped": []}
    results_negative = {"perplexity": None, "tavily": None, "scraped": []}
# ↑ далее LLM вызывается на пустых данных → hallucination
```

**После:**

```python
try:
    results_general = await _search_multi_provider(queries["general"])
    results_courts = await _search_multi_provider(queries["courts"])
    results_negative = await _search_multi_provider(queries["negative"])
except Exception:
    results_general = {"perplexity": None, "tavily": None, "scraped": []}
    results_courts = {"perplexity": None, "tavily": None, "scraped": []}
    results_negative = {"perplexity": None, "tavily": None, "scraped": []}

# cycle-5/D-AUDIT-503 (BL-P0-002): fail-CLOSED — если все 3 search providers
# вернули None/empty, НЕ вызываем LLM (иначе LLM галлюцинирует отчёт без фактов).
if _all_search_results_empty(results_general, results_courts, results_negative):
    logger.error("osint_search_insufficient_data", extra={"inn": inn, "company_name": company_name})
    raise InsufficientDataError(
        f"All 3 search providers returned empty results for INN {inn!r}"
    )
```

**Helper:**

```python
def _all_search_results_empty(*results: dict[str, Any]) -> bool:
    """cycle-5/D-AUDIT-503: True если во всех 3 search-результатах все провайдеры пусты."""
    for r in results:
        if not isinstance(r, dict):
            return False
        for key in ("perplexity", "tavily", "scraped"):
            value = r.get(key)
            if value not in (None, [], {}, ""):
                return False
    return True
```

**Domain exception** (cycle-5/D-AUDIT-503):

```python
class InsufficientDataError(Exception):
    """Search providers вернули пустые данные — fail-CLOSED до LLM-вызова."""
```

### 2.3 Module docstring + docstring markers

**Module docstring** (cycle-5/D-AUDIT-503):

```python
"""OSINT workflow: validate INN, web-search, compose report via LLM.
...
Fail-CLOSED contract (cycle-5/D-AUDIT-503):
- Если search вернул пустые данные — raise InsufficientDataError ДО LLM,
  чтобы LLM не галлюцинировал отчёт без фактов.
- Если LLM недоступен — raise LLMUnavailableError (НЕ возвращать prompt
  template как report).
"""
```

**`run_osint` docstring** (updated `Raises:` section):

```python
Raises:
    ValueError: If INN is invalid.
    InsufficientDataError: All search providers returned empty (cycle-5/D-AUDIT-503).
        Caller should treat as ``{"status": "insufficient_data", "report": None}``.
    LLMUnavailableError: LLM gateway failed (cycle-5/D-AUDIT-503). Caller should
        treat as ``{"status": "insufficient_data", "report": None}``.
```

### 2.4 Tests added (8 total)

`TestAllSearchResultsEmpty` (4 tests) — helper unit tests:

- `test_all_none_is_empty` — все None providers → True
- `test_one_provider_with_data_is_not_empty` — один провайдер с данными → False
- `test_non_dict_arg_is_not_empty` — non-dict arg → False (defensive)
- `test_empty_dict_treated_as_empty` — пустые {} для каждого → True

`TestRunOsintFailClosed` (4 tests) — integration:

- `test_llm_failure_raises_unavailable_no_template_echo` — mock LLM raises → expect `LLMUnavailableError`, verify message NOT contains "OSINT_REPORT_TEMPLATE" (no template echo)
- `test_empty_search_results_raises_insufficient_data_no_llm` — mock search returns empty → expect `InsufficientDataError`, verify `llm_called is False` (LLM NOT invoked)
- `test_search_failure_initializes_empty_then_insufficient_data` — outer except path → search provider `ConnectionError` → InsufficientDataError
- `test_partial_results_one_provider_has_data_passes_guard` — guard requires ALL empty → one provider with data → report returned (no InsufficientDataError)

---

## 3. Diff stat

```bash
$ git diff --stat extensions/osint_agent/
 extensions/osint_agent/functions/osint_workflow.py |  60 +++++++-
 extensions/osint_agent/tests/test_osint_workflow.py | 171 +++++++++++++++++++++
 2 files changed, 229 insertions(+), 2 deletions(-)
```

**Minimal change footprint:**
- `osint_workflow.py`: +58/-2 (2 new exception classes, 1 helper, 2 fail-CLOSED guards, module docstring update)
- `test_osint_workflow.py`: +171/-0 (8 new tests, 2 new imports)

---

## 4. Verification

### 4.1 New tests (8/8 PASS)

```bash
$ .venv/bin/python -m pytest extensions/osint_agent/tests/test_osint_workflow.py::TestAllSearchResultsEmpty \
    extensions/osint_agent/tests/test_osint_workflow.py::TestRunOsintFailClosed -v

extensions/osint_agent/tests/test_osint_workflow.py::TestAllSearchResultsEmpty::test_all_none_is_empty PASSED
extensions/osint_agent/tests/test_osint_workflow.py::TestAllSearchResultsEmpty::test_one_provider_with_data_is_not_empty PASSED
extensions/osint_agent/tests/test_osint_workflow.py::TestAllSearchResultsEmpty::test_non_dict_arg_is_not_empty PASSED
extensions/osint_agent/tests/test_osint_workflow.py::TestAllSearchResultsEmpty::test_empty_dict_treated_as_empty PASSED
extensions/osint_agent/tests/test_osint_workflow.py::TestRunOsintFailClosed::test_llm_failure_raises_unavailable_no_template_echo PASSED
extensions/osint_agent/tests/test_osint_workflow.py::TestRunOsintFailClosed::test_empty_search_results_raises_insufficient_data_no_llm PASSED
extensions/osint_agent/tests/test_osint_workflow.py::TestRunOsintFailClosed::test_search_failure_initializes_empty_then_insufficient_data PASSED
extensions/osint_agent/tests/test_osint_workflow.py::TestRunOsintFailClosed::test_partial_results_one_provider_has_data_passes_guard PASSED

============================== 8 passed in 4.42s ===============================
```

### 4.2 All OSINT tests (26 PASS, 2 pre-existing FAIL)

```bash
$ .venv/bin/python -m pytest extensions/osint_agent/tests/ tests/unit/extensions/test_osint_workflow_waf_coverage.py -v
...
FAILED extensions/osint_agent/tests/test_osint_workflow.py::TestValidateInn::test_valid_12_digit_inn
FAILED extensions/osint_agent/tests/test_osint_workflow.py::TestValidateInn::test_none_inn
========================= 2 failed, 26 passed in 3.60s =========================
```

**Pre-existing failures** (NOT from this work, both out of cycle-5 scope per BL-P2-002 / BL-P1-003 in cycle-4 phase-1 report):

- `test_valid_12_digit_inn` — invalid test data `"770708389307"` (TEST BUG, не code bug per BL-P2-002)
- `test_none_inn` — `validate_inn(None)` raises TypeError instead of returning False (per BL-P1-003, требует правки `src/backend/dsl/helpers/banking.py`)

### 4.3 All extensions tests (91 PASS, 3 pre-existing FAIL)

```bash
$ .venv/bin/python -m pytest extensions/ -q
3 failed, 91 passed in 3.64s
```

Pre-existing failures (NOT from this work):
- `test_credit_pipeline_v2_flag_exists_and_default_off` (BL-P2-003 / cycle-3 T-09 RESIDUAL)
- 2 OSINT test data / `validate_inn(None)` (см. 4.2)

**Cycle-5 introduced 8 new tests, все 8 PASS, 0 regressions.**

### 4.4 Docstring gate

```bash
$ make check-docstrings MAX_ALLOWED=0
uv virtual environment detected
Running docstring policy check...
Total: 0 missing docstrings in 0 files
Files scanned: 840
docstring policy OK
EXIT: 0
```

### 4.5 Layer checker (175/0 baseline preserved)

```bash
$ bash tools/cycle-1-preflight.sh
cycle-1 preflight (T-0.1 re-run):
  [OK]   layer checker — 0 new, 175 legacy
  [OK]   allowlist active IDs — 27
  [OK]   docstring gate — 0 missing
  [FAIL] working tree — 36 entries (разобраться)    ← pre-existing drift (cycle-1+2+3+4 mods в working tree)
  [FAIL] uv.lock churn — 45 lines (проверить не растёт ли)  ← pre-existing
  [OK]   s3.py untouched — не modified
```

**Layer check OK** (175/0 baseline preserved). Working tree + uv.lock failures pre-existing (modified files: `services/ai/ai_agent/__init__.py`, `agent_security/facade.py`, `temporal_backend.py`, etc. — все pre-existing modifications from cycles 1+2+3+4; НЕ от cycle-5).

### 4.6 Forbidden files — все untouched

| File | Status |
|---|---|
| `uv.lock` | НЕ изменён в этой работе (пред-существующая модификация — pre-baseline churn) |
| `.security/pip-audit-allowlist.txt` | НЕ изменён |
| `src/backend/infrastructure/storage/s3.py` | НЕ изменён |
| `tools/blue_green.sh` | НЕ изменён |
| `tests/unit/tools/test_blue_green_switch.py` | НЕ изменён |

### 4.7 Layer violations — 0

Cycle-5 work — только `extensions/osint_agent/` (внутри extension scope). Нет новых cross-layer imports.

### 4.8 `except Exception` — без удаления

Все 5 `except Exception` в `osint_workflow.py` (per BL-P3-001) — сохранены. Cycle-5 добавил **2 новых** `except Exception` с **concrete handling** (logger.error + raise доменного exception). Это не удаление broad except, а конкретизация с fail-CLOSED output.

---

## 5. Что НЕ сделано (явно вне scope)

1. **BL-P1-001** (orders_dsl `.then()` AttributeError) — другой workstream (`extensions/core_entities/`), не мой домен.
2. **BL-P1-002** (TenantFacade kwargs) — `src/backend/services/tenancy/facade.py`, не в extensions scope. Зафиксировано как T-08 RESIDUAL в PHASE-2-SUMMARY §5.1.
3. **BL-P1-003** (validate_inn None guard) — `src/backend/dsl/helpers/banking.py`, не в extensions scope.
4. **BL-P2-001** (SagaDeclaration dead import) — orders_dsl.py, не мой домен.
5. **BL-P2-002** (invalid 12-digit INN test data) — test data fix, не code fix.
6. **BL-P2-003** (credit_pipeline_v2 default) — `core/config/features/plugins.py`, не в extensions scope.
7. **BL-P2-004** (silent ES indexing) — orders/services, не мой домен.
8. **BL-P3-001** (broad except — 5×) — оставлены как есть (graceful degradation допустим для external HTTP search/scraping).
9. **BL-P3-002** (silent audit emission в credit_pipeline) — другой extension, не мой домен.
10. **BL-P4-001** (3 workflow YAML без loaders) — architectural decision, defer.

---

## 6. Команды запуска (reproduce)

```bash
# 1. Run new fail-CLOSED tests:
.venv/bin/python -m pytest extensions/osint_agent/tests/test_osint_workflow.py::TestAllSearchResultsEmpty \
    extensions/osint_agent/tests/test_osint_workflow.py::TestRunOsintFailClosed -v

# 2. Run all OSINT tests:
.venv/bin/python -m pytest extensions/osint_agent/tests/ \
    tests/unit/extensions/test_osint_workflow_waf_coverage.py -v

# 3. Run all extensions tests:
.venv/bin/python -m pytest extensions/ -q

# 4. Docstring gate:
make check-docstrings MAX_ALLOWED=0

# 5. Preflight (NOTE: pre-existing drift will keep "working tree" + "uv.lock"
#    checks failing, these are NOT from cycle-5):
bash tools/cycle-1-preflight.sh
```

---

## 7. Готовность к phase-3

- **BL-P0-001** (OSINT LLM fail-OPEN) — ✅ **RESOLVED** (cycle-5)
- **BL-P0-002** (OSINT search fail-OPEN / hallucination) — ✅ **RESOLVED** (cycle-5)
- OSINT теперь **fail-CLOSED** по обоим критичным путям.
- 8/8 новых тестов PASS, 0 regressions, 0 layer violations, 0 docstring debt.
- Готовность бизнес-логики блокируется оставшимися P1+P2 findings (вне scope cycle-5).

---

## 8. Compliance note

- **PII**: OSINT workflow не хранит PII — только публичные данные (ИНН, наименование, ИНН-валидация).
- **Audit**: `logger.error("osint_llm_unavailable", ...)` / `logger.error("osint_search_insufficient_data", ...)` — observability для compliance audit trail. Audit emission через `emit_audit_safe` НЕ добавлен (per minimal-edit mode и отсутствие explicit `core.audit` facade requirement в плане).
- **Cycle-1+2+3+4 fixes НЕ переписаны**: `extensions/osint_agent/functions/osint_workflow.py` cycle-1 `_scrape_url` через OutboundHttpClient (D-AUDIT-A2-02) сохранён без изменений.

---

**Report:** `docs/audit/swarm-2026-08-06/cycle-5/cycle-5-D-AUDIT-503-report.md`
**Author:** Kimi Code CLI (cycle-5 dev agent, business-logic domain)
**Date:** 2026-08-07
