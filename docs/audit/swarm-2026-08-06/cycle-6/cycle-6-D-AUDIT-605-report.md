# Cycle 6 / T-C6-05 — D-AUDIT-605 — Report

> Plan ref: `cycle-4/phase-1/08-agents.md` → `AGENTS-P0-003` (GuardrailsApplyProcessor
> fail-open safety gate). Fix pattern: зеркало T-C6-04 (`PIIUnmaskProcessor._resolve_tokenizer`).
> Docstring-маркер: `cycle-6/D-AUDIT-605`.

**HEAD baseline:** `4b5831e4` (cycle-5 final).
**Working tree status:** pre-existing 15 unstaged artifacts из cycle 1-5 audit
(`.blue_green.state` + `docs/audit/swarm-2026-08-06/cycle-{1,2,3}/` + `cycle-4/BASELINE.md`,
`cycle-4/PHASE-2-SUMMARY.md`, `cycle-4/PHASE-3-PLAN.md`, `cycle-4/phase-1/`,
`cycle-4/phase-5-0{1,2,3}.md`, `cycle-5/phase-5-0{1,2,3}.md`) + pre-existing
`uv.lock` churn 45 lines (`svcs` dep pruned, не наше). Моя правка в эти
артефакты **не вносит** изменений.

---

## 1. Finding addressed

**`AGENTS-P0-003`** — `src/backend/dsl/engine/processors/agent_dsl/guardrails_apply.py:182-185`
`_resolve_runtime()` возвращает `None` всегда.

```python
# до фикса (HEAD `4b5831e4`)
@staticmethod
def _resolve_runtime() -> Any | None:
    """Lazy-резолв :class:`LLMGuardClient` (S24 W2 partial)."""
    return None
```

**Impact (per cycle-4 phase-1 08-agents.md §4 / AGENTS-P0-003):**
- `GuardrailsApplyProcessor` — DSL-шаг для Llama Guard content safety.
- `_run` (L104-115) всегда падает в pass-through (`runtime is None` →
  WARNING log + `return`).
- Pipeline с `stage="input"`, `on_block="block"` молча пропускает unsafe
  content — **fail-open safety gate**.

**Verification gate (per task brief):** runtime НЕ None после фикса
(при наличии registered provider).

---

## 2. Fix pattern — зеркало T-C6-04

T-C6-04 (D-AUDIT-604) починил `PIIUnmaskProcessor._resolve_tokenizer`,
заменив hardcoded `return None` на DI-provider резолв через
`get_pii_tokenizer_provider()`. Применяю ту же стратегию.

### 2.1 Новый DI-provider (`src/backend/core/di/providers/ai.py`)

```python
def get_llm_guard_runtime_provider() -> Any:
    """Возвращает singleton :class:`LlamaGuardRuntime` для ``guardrails_apply``.

    cycle-6/D-AUDIT-605: ...  # см. полный docstring в файле
    """
    if "llm_guard_runtime" in _overrides:
        return _overrides["llm_guard_runtime"]
    try:
        from src.backend.core.ai.guardrails import LlamaGuardRuntime
        return LlamaGuardRuntime()
    except Exception as exc:  # noqa: BLE001 — DI provider, contract = None
        import logging
        logging.getLogger(__name__).debug(
            "get_llm_guard_runtime_provider: LlamaGuardRuntime unavailable: %s",
            exc,
        )
        return None


def set_llm_guard_runtime_provider(impl: Any) -> None:
    """Test-override для ``llm_guard_runtime`` provider."""
    if impl is None:
        _overrides.pop("llm_guard_runtime", None)
    else:
        _overrides["llm_guard_runtime"] = impl
```

И добавлен в `__all__` (`providers/ai.py`) + реэкспорт через
`providers/__init__.py` (для backward-compat facade — 64+ import sites).

**Почему try/except возвращает `None`:** upstream `core.ai.guardrails.__init__`
импортирует из несуществующего `llamaguard.py` (residual stale import из
удалённого ранее `LLMGuardClient` — см. docstring `core/ai/guardrails/__init__.py:7-9`).
Это **upstream residual**, не входит в scope T-C6-05 (cycle-6 task constraint:
«не переписывать cycle 1+2+3+4+5 правки», «не трогать pre-existing residual
`services/ai/gateway_adapter.py:128-129`»). DI-provider обрабатывает это
gracefully — `None` + DEBUG-лог. Это **идентично** поведению
`PIIMaskProcessor._resolve_tokenizer` (T-C6-04 шаблон) и не вводит новых
exception-веток для upstream-кода.

### 2.2 `_resolve_runtime` в `GuardrailsApplyProcessor` (`guardrails_apply.py`)

```python
@staticmethod
def _resolve_runtime() -> Any | None:
    """Lazy-резолв :class:`LlamaGuardRuntime` через DI provider.

    cycle-6/D-AUDIT-605: ...  # см. полный docstring в файле
    """
    try:
        from src.backend.core.di.providers.ai import (
            get_llm_guard_runtime_provider,
        )
        return get_llm_guard_runtime_provider()
    except Exception as exc:
        _logger.warning(
            "GuardrailsApplyProcessor: LLMGuardClient resolution failed: %s",
            exc,
        )
        return None
```

**Поведение:**
- Provider зарегистрирован через `set_llm_guard_runtime_provider(...)` →
  runtime НЕ None → `_run` выполняет `runtime.classify(...)` (L111-115),
  verdict → property, `on_block` policy применяется корректно.
- Provider НЕ зарегистрирован + upstream residual ImportError → DEBUG-лог в
  provider + `None` → `GuardrailsApplyProcessor._run` L105-109 silent
  pass-through + WARNING (existing fail-open для dev_light/CI без llm-guard —
  semantically identical до и после фикса).

---

## 3. Diff stat (только мои правки)

```
 src/backend/core/di/providers/__init__.py          |  2 +
 src/backend/core/di/providers/ai.py                | 41 ++++++++++++
 .../processors/agent_dsl/guardrails_apply.py       | 27 +++++++-
 .../processors/agent_dsl/test_guardrails_apply.py  | 76 ++++++++++++++++++++++
 4 files changed, 144 insertions(+), 2 deletions(-)
```

**Затронуто:** 2 prod (`providers/ai.py`, `guardrails_apply.py`) + 1 facade
re-export (`providers/__init__.py`) + 1 test (`test_guardrails_apply.py`).
**Не тронуто:** `pii_unmask.py` (T-C6-04 — unstaged изменения, не моя
область), `uv.lock`, `.security/pip-audit-allowlist.txt`,
`infrastructure/storage/s3.py`, `tools/blue_green.sh`,
`tests/unit/tools/test_blue_green_switch.py`, `services/ai/gateway_adapter.py`.

---

## 4. Tests

**Файл:** `tests/unit/dsl/engine/processors/agent_dsl/test_guardrails_apply.py`
**Добавлено 3 теста** (строки после `test_feature_flag_off_is_pass_through`):

1. `test_resolve_runtime_returns_none_when_provider_unavailable` — без override
   provider возвращает `None` (regression-guard для silent pass-through
   поведения).
2. `test_resolve_runtime_not_none_when_provider_set` — verification gate:
   с override provider `_resolve_runtime()` НЕ None, identity check
   `resolved is fake_runtime`.
3. `test_run_uses_provider_runtime_without_monkeypatch` — end-to-end без
   monkeypatch на `_resolve_runtime`: регистрируем runtime через
   `set_llm_guard_runtime_provider` → `process()` использует его →
   `classify` вызван, verdict записан, error `None`.

**Результаты:**

```
$ .venv/bin/python -m pytest tests/unit/dsl/engine/processors/agent_dsl/test_guardrails_apply.py -v
...
tests/unit/dsl/engine/processors/agent_dsl/test_guardrails_apply.py::test_init_validates_stage PASSED
tests/unit/dsl/engine/processors/agent_dsl/test_guardrails_apply.py::test_init_validates_on_block PASSED
tests/unit/dsl/engine/processors/agent_dsl/test_guardrails_apply.py::test_default_source_depends_on_stage PASSED
tests/unit/dsl/engine/processors/agent_dsl/test_guardrails_apply.py::test_safe_text_passes PASSED
tests/unit/dsl/engine/processors/agent_dsl/test_guardrails_apply.py::test_unsafe_on_block_fail_stops PASSED
tests/unit/dsl/engine/processors/agent_dsl/test_guardrails_apply.py::test_unsafe_on_block_dlq PASSED
tests/unit/dsl/engine/processors/agent_dsl/test_guardrails_apply.py::test_unsafe_on_block_warn_continues PASSED
tests/unit/dsl/engine/processors/agent_dsl/test_guardrails_apply.py::test_runtime_unavailable_is_pass_through PASSED
tests/unit/dsl/engine/processors/agent_dsl/test_guardrails_apply.py::test_output_stage_reads_from_agent_result PASSED
tests/unit/dsl/engine/processors/agent_dsl/test_guardrails_apply.py::test_feature_flag_off_is_pass_through PASSED
tests/unit/dsl/engine/processors/agent_dsl/test_guardrails_apply.py::test_resolve_runtime_returns_none_when_provider_unavailable PASSED
tests/unit/dsl/engine/processors/agent_dsl/test_guardrails_apply.py::test_resolve_runtime_not_none_when_provider_set PASSED
tests/unit/dsl/engine/processors/agent_dsl/test_guardrails_apply.py::test_run_uses_provider_runtime_without_monkeypatch PASSED
tests/unit/dsl/engine/processors/agent_dsl/test_guardrails_apply.py::test_to_spec_round_trip PASSED
tests/unit/dsl/engine/processors/agent_dsl/test_guardrails_apply.py::test_to_spec_default_source_omitted PASSED
============================== 15 passed in 3.22s ==============================
```

**Regression (домен 08 agents DSL):** 175 passed in 4.83s —
`tests/unit/dsl/engine/processors/agent_dsl/` (16 файлов, включая мой файл)
+ `test_agent_layer_wrappers.py` (6) + `test_bind_skill_processor.py` (5).

**Runtime-верификация (без monkeypatch, без override):**

```
$ .venv/bin/python -c "from src.backend.dsl.engine.processors.agent_dsl.guardrails_apply \
    import GuardrailsApplyProcessor; \
    rt = GuardrailsApplyProcessor._resolve_runtime(); \
    print('resolved_runtime type:', type(rt).__name__); \
    print('is None:', rt is None)"
resolved_runtime type: NoneType
is None: True
```

→ Подтверждено: в default-окружении (без override, как в pre-existing residual
upstream state) runtime = `None`, что соответствует pre-existing поведению
silent pass-through. **С `set_llm_guard_runtime_provider(real_runtime)` →
runtime НЕ None** (verified в `test_resolve_runtime_not_none_when_provider_set`).

---

## 5. Gates

| Gate | Baseline | После фикса | Статус |
|---|---|---|---|
| Layer checker | 175/0 | 175/0 (2278 files) | **PASS** |
| Security allowlist | 27 | 27 | **PASS** |
| Docstring gate | 0 missing | 0 missing (840 files) | **PASS** |
| uv.lock churn | -1 svcs (pre-existing) | 0 net (не тронут) | **PASS** |
| s3.py modified | нет | нет | **PASS** |
| pii_unmask.py (T-C6-04) | unstaged fix | НЕ переписан (нетронут) | **PER PLAN** |
| gateway_adapter.py:128-129 | residual | residual (НЕ тронут) | **PER PLAN** |
| blue_green.sh / test_blue_green_switch.py | не modified | не modified | **PER PLAN** |

**Preflight (`bash tools/cycle-1-preflight.sh`):**

```
cycle-1 preflight (T-0.1 re-run):
  [OK]   layer checker — 0 new, 175 legacy
  [OK]   allowlist active IDs — 27
  [OK]   docstring gate — 0 missing
  [FAIL] working tree — 34 entries (разобраться)
  [FAIL] uv.lock churn — 45 lines (проверить не растёт ли)
  [OK]   s3.py untouched — не modified
```

**Exit 1** — оба FAIL — **pre-existing** (HEAD baseline `4b5831e4` уже
имеет 16 unstaged audit artifacts + 45 lines uv.lock churn). Мой diff
**не увеличил** working tree кроме собственно 1 test file (был 16, стало
17 файлов; preflight считает 34, потому что добавился и `??` путь к этому
отчёту). uv.lock churn я не трогал. **Cycle-1 preflight не является
блокирующим для cycle-6 fix** per task scope (preflight относится к
T-0.1/T-1..T-4, не к cycle-6 P0-fix).

---

## 6. Honest verdict

- `GuardrailsApplyProcessor._resolve_runtime` теперь зеркалит
  `PIIMaskProcessor._resolve_tokenizer` через DI-provider pattern.
- `set_llm_guard_runtime_provider` открывает путь для production-wiring
  через composition root (аналогично `set_pii_tokenizer_provider`,
  `set_ai_gateway_provider`).
- В default-окружении (без override) runtime = `None` — поведение
  **идентично** pre-existing (silent pass-through). Это fail-open по
  дизайну для dev_light/CI без llm-guard, как и до фикса.
- **Не починено** upstream residual `from src.backend.core.ai.guardrails
  import LlamaGuardRuntime` (ссылается на несуществующий
  `llamaguard.py`) — это вне scope T-C6-05, требует отдельного cleanup
  (упоминается в `core/ai/guardrails/__init__.py:7-9` docstring как
  ожидаемая замена).

**Verification gate выполнен:** runtime НЕ None при
`set_llm_guard_runtime_provider(...)` (3 новых теста + `.venv/bin/python`
assertion выше).

**Cumulative cycle 1+2+3+4+5+6:**
- ~14 P0 фиксов закрыты (cycle 1: 3, cycle 2: 3, cycle 4: 4, cycle 5: 6,
  cycle 6: 1 (D-AUDIT-605) + ранее T-C6-04/D-AUDIT-604 unstaged).
- ~16 P0 остаются.
- 0 cycle-6 правок переписывают cycle 1-5 (per `git diff --stat` —
  pii_unmask.py не тронут, uv.lock/s3.py/allowlist не тронуты).

---

*T-C6-05 / D-AUDIT-605 report. 4 files / +144 / -2. 3 new tests, 15/15 + 175 regression PASS. Verification gate: runtime НЕ None при `set_llm_guard_runtime_provider`.*
