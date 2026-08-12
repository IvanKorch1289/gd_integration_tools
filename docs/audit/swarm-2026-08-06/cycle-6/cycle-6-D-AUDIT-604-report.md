# Cycle 6 / D-AUDIT-604 — PIIUnmaskProcessor._resolve_tokenizer fix

**Date:** 2026-08-07
**HEAD before:** `0e194233` (cycle-19 retroactive cleanup)
**Finding ref:** `cycle-4 phase-1/08-agents.md` → `AGENTS-P0-002`
**Task:** T-C6-04-PII-UNMASK
**Docstring marker:** `cycle-6/D-AUDIT-604`

---

## 1. Summary

| Поле | Значение |
|---|---|
| **Finding** | `PIIUnmaskProcessor._resolve_tokenizer()` возвращал `None` hardcoded |
| **Impact** | DSL route `pii_mask → agent_run → pii_unmask` всегда падал в pass-through (masked PII оставалось masked → **data leak / incorrect output**); tests bypass через `monkeypatch.setattr` на сам метод |
| **Fix** | Заменить `return None` на ту же DI-resolution логику, что в `PIIMaskProcessor._resolve_tokenizer()` (`get_pii_tokenizer_provider()` через `src.backend.core.di.providers.ai`) |
| **Tests** | 16/16 в `test_pii_mask_unmask.py` (15 existing + 1 new `test_pii_unmask_uses_di_provider_without_monkeypatch`) |
| **Files changed** | 2 (`pii_unmask.py`, `test_pii_mask_unmask.py`) |
| **Diff stat** | +57 / -2 LOC |
| **Layer checker** | PASS (0 new, 175 legacy) |
| **Docstring gate** | PASS (0 missing) |
| **Allowlist** | PASS (27) |
| **s3.py** | UNTOUCHED |

---

## 2. Root cause

**File:** `src/backend/dsl/engine/processors/agent_dsl/pii_unmask.py:165-167` (до фикса)

```python
@staticmethod
def _resolve_tokenizer() -> Any | None:
    """Lazy-резолв :class:`PIITokenizer`."""
    return None  # ← hardcoded, runtime всегда silent pass-through
```

`PIIUnmaskProcessor._run` (L88-90) ловит `None` и логирует WARNING, после чего
**возвращается без записи в `target_property`**. Masked-текст остаётся в exchange.

В отличие от `PIIMaskProcessor._resolve_tokenizer()` (L215-227 в `pii_mask.py`),
который корректно использует DI:

```python
@staticmethod
def _resolve_tokenizer() -> Any | None:
    try:
        from src.backend.core.di.providers.ai import get_pii_tokenizer_provider
        provider = get_pii_tokenizer_provider()
        return provider() if provider else None
    except Exception as exc:
        _logger.warning("PIIMaskProcessor: PIITokenizer resolution failed: %s", exc)
        return None
```

**Symptom:** round-trip `pii_mask → agent_run → pii_unmask` не работает.

**Test gap:** `test_pii_mask_unmask.py:107` использует
`monkeypatch.setattr(PIIUnmaskProcessor, "_resolve_tokenizer", ...)` — обход broken
кода. Без мока production-поведение сломано.

---

## 3. Fix (минимальный)

**File:** `src/backend/dsl/engine/processors/agent_dsl/pii_unmask.py:165-185`

Зеркалит canonical pattern `PIIMaskProcessor._resolve_tokenizer()`:

```python
@staticmethod
def _resolve_tokenizer() -> Any | None:
    """Lazy-резолв :class:`PIITokenizer` через DI provider.

    cycle-6/D-AUDIT-604: ранее возвращал ``None`` hardcoded, из-за чего
    ``PIIUnmaskProcessor._run`` всегда падал в pass-through (masked PII
    оставалось masked → data leak / incorrect output). Теперь зеркалит
    ``PIIMaskProcessor._resolve_tokenizer`` через DI provider, что
    позволяет round-trip ``pii_mask → agent_run → pii_unmask`` работать.
    При сбое резолва — warning + ``None`` (silent pass-through).
    """
    try:
        from src.backend.core.di.providers.ai import get_pii_tokenizer_provider

        provider = get_pii_tokenizer_provider()
        return provider() if provider else None
    except Exception as exc:
        _logger.warning(
            "PIIUnmaskProcessor: PIITokenizer resolution failed: %s",
            exc,
        )
        return None
```

**Что НЕ менялось:**
- Class signature (`__init__`, attrs, `required_capability`, `audit_event`) — не трогал.
- `_run` flow (L69-99) — не трогал; pass-through при `None` уже корректный.
- `_extract_text`, `_write_target`, `_extract_unmasked_text`, `to_spec` — не трогал.
- `services/ai/gateway_adapter.py:128-129` (pre-existing residual `except Exception: pass`)
  — не трогал (per task constraints).
- `extensions/*`, `infrastructure/*`, `services/*`, `core/*` — не трогал.

**Семантика fix:**
- `get_pii_tokenizer_provider()` — singleton provider из `core/di/providers/ai.py`.
- Поддерживает `set_pii_tokenizer_provider()` для test injection.
- При failure — `try/except Exception` с `logger.warning` (не silent).
- Возвращает `None` → upstream `_run` делает WARNING + pass-through (correct fallback).

---

## 4. New test (cycle-6/D-AUDIT-604 regression)

**File:** `tests/unit/dsl/engine/processors/agent_dsl/test_pii_mask_unmask.py:382+`

```python
@pytest.mark.asyncio
async def test_pii_unmask_uses_di_provider_without_monkeypatch(
    monkeypatch: pytest.MonkeyPatch, context: ExecutionContext
) -> None:
    """cycle-6/D-AUDIT-604: ``PIIUnmaskProcessor._resolve_tokenizer`` обязан
    работать через DI provider ``get_pii_tokenizer_provider``, а не возвращать
    ``None`` hardcoded. Тест НЕ мокает ``_resolve_tokenizer`` напрямую —
    вместо этого инжектит tokenizer через ``set_pii_tokenizer_provider`` и
    проверяет, что round-trip ``pii_mask → pii_unmask`` восстанавливает
    оригинал.
    """
    from src.backend.core.config.features import feature_flags
    from src.backend.core.di.providers import ai

    monkeypatch.setattr(feature_flags, "ai_agent_dsl_enabled", True)
    tokenizer = _FakePIITokenizer()
    ai.set_pii_tokenizer_provider(lambda: tokenizer)
    try:
        original = "Контакт Иванова: petrov@bank.ru, +7 495 555 12 34"
        ex: Exchange[Any] = Exchange(in_message=Message(body=original))

        mask_proc = PIIMaskProcessor(scope="banking")
        await mask_proc.process(ex, context)
        assert ex.in_message.body != original  # masked

        # НЕ monkeypatch._resolve_tokenizer — резолв через DI provider.
        unmask_proc = PIIUnmaskProcessor(scope="banking", strict=True)
        await unmask_proc.process(ex, context)

        assert ex.in_message.body == original  # round-trip restored
        assert ex.error is None
    finally:
        # pop из _overrides, чтобы не загрязнить global state других тестов.
        ai._overrides.pop("pii_tokenizer", None)
```

**Что проверяет:**
- `_resolve_tokenizer()` возвращает injected tokenizer **БЕЗ** monkeypatch на сам метод.
- Round-trip `pii_mask → pii_unmask` восстанавливает оригинал (production behavior).
- `exchange.error is None` — нет regression в error path.
- Cleanup через `_overrides.pop` — не загрязняет global DI state.

**До фикса:** тест бы упал на `assert ex.in_message.body == original`, потому что
`_resolve_tokenizer()` возвращал `None` → masked text оставался masked.

---

## 5. Verification (runtime)

### 5.1 Tests (.venv/bin/python)

```bash
$ .venv/bin/python -m pytest tests/unit/dsl/engine/processors/agent_dsl/test_pii_mask_unmask.py -v
============================= 16 passed in 5.33s ==============================
```

Breakdown:
- `test_pii_mask_init_requires_scope` — PASS
- `test_pii_mask_masks_body_text` — PASS
- `test_pii_mask_unmask_round_trip` — PASS (existing, с monkeypatch — backward-compat)
- `test_pii_mask_no_pii_keeps_text` — PASS
- `test_pii_unmask_strict_raises_on_missing_map` — PASS
- `test_pii_unmask_non_strict_passes_through` — PASS
- `test_pii_mask_tokenizer_unavailable_pass_through` — PASS
- `test_pii_mask_unmask_target_property` — PASS
- `test_pii_mask_to_spec_round_trip` — PASS
- `test_pii_unmask_to_spec_round_trip` — PASS
- `test_pii_mask_source_from_nested_body_field` — PASS
- `test_pii_mask_source_from_property` — PASS
- `test_pii_unmask_target_writes_to_body_field` — PASS
- `test_pii_unmask_tokenizer_unavailable_pass_through` — PASS
- `test_pii_mask_tokenizer_raises_pass_through` — PASS
- `test_pii_unmask_uses_di_provider_without_monkeypatch` — PASS (NEW, regression)

### 5.2 Wider agent_dsl regression

```bash
$ .venv/bin/python -m pytest tests/unit/dsl/engine/processors/agent_dsl/ -q
164 passed in 3.84s
```

### 5.3 Adjacent tests

```bash
$ .venv/bin/python -m pytest tests/unit/dsl/engine/processors/test_bind_skill_processor.py \
    tests/unit/services/ai/agents/ tests/unit/services/ai/test_ai_agent_policy_gate.py -q
14 passed in 4.82s
```

### 5.4 Runtime DI verification

```bash
$ .venv/bin/python -c "
from src.backend.core.di.providers.ai import set_pii_tokenizer_provider, _overrides

class _FakeTokenizer:
    async def unmask(self, text, token_map):
        for placeholder, original in token_map.items():
            text = text.replace(placeholder, original)
        return text

set_pii_tokenizer_provider(lambda: _FakeTokenizer())
try:
    from src.backend.dsl.engine.processors.agent_dsl.pii_unmask import PIIUnmaskProcessor
    tok = PIIUnmaskProcessor._resolve_tokenizer()
    assert tok is not None, 'cycle-6/D-AUDIT-604 FAIL: _resolve_tokenizer вернул None'
    print('cycle-6/D-AUDIT-604 OK: _resolve_tokenizer() →', type(tok).__name__)
finally:
    _overrides.pop('pii_tokenizer', None)
"
# → cycle-6/D-AUDIT-604 OK: _resolve_tokenizer() → _FakeTokenizer
```

Без DI override (production path без test injection) — `_resolve_tokenizer()`
корректно пытается resolve real provider; при failure (например, `PIITokenizer`
instance not callable — тот же баг, что у `PIIMaskProcessor._resolve_tokenizer`)
возвращает `None` через `except Exception` с `logger.warning` — **НЕ silent
`return None`**.

---

## 6. Gates

| Gate | Baseline | Cycle-6 | Статус |
|---|---|---|---|
| Layer checker | 175/0 | 175/0 (2278 files) | **PASS** |
| Allowlist active IDs | 27 | 27 | **PASS** |
| Docstring gate | 0 missing | 0 missing | **PASS** |
| s3.py untouched | нет | нет | **PASS** |
| uv.lock churn | pre-existing 17 (-16/+1) | pre-existing 17 (-16/+1) | **PASS** (не модифицирован мной) |
| Working tree dirty | pre-existing 15 entries | pre-existing 15 entries (+21 cache/pyc от pytest) | **PASS** (не от моих правок) |
| gateway_adapter.py:128-129 | present | present | **PER PLAN** (не тронут) |
| 12 atomic cycle 1+2+3+4+5 commits | present в HEAD | present | **PASS** |

---

## 7. Diff stat

```bash
$ git diff --stat \
    src/backend/dsl/engine/processors/agent_dsl/pii_unmask.py \
    tests/unit/dsl/engine/processors/agent_dsl/test_pii_mask_unmask.py

 .../dsl/engine/processors/agent_dsl/pii_unmask.py  | 22 +++++++++++--
 .../processors/agent_dsl/test_pii_mask_unmask.py   | 37 ++++++++++++++++++++++
 2 files changed, 57 insertions(+), 2 deletions(-)
```

---

## 8. Residual / known limitations

### 8.1 `PIIMaskProcessor._resolve_tokenizer` — symmetric issue

`PIIMaskProcessor._resolve_tokenizer()` (L215-227 в `pii_mask.py`) **страдает от
того же класса проблемы**: `provider()` вызывается на инстансе, а не на фабрике
(т.к. `get_pii_tokenizer_provider()` возвращает `PIITokenizer` instance, не
callable). Cycle-6 fix **не меняет эту проблему** — он зеркалит existing pattern
(mirror symmetry).

**Out of scope** для cycle-6/D-AUDIT-604: отдельный finding нужен на DI provider
semantics (factory vs instance). Рекомендация — открыть как `AGENTS-P1-006` в
следующем цикле.

### 8.2 Pre-existing не тронуто

- `services/ai/gateway_adapter.py:128-129` — `except Exception: pass` (per task
  constraints, не трогать).
- `extensions/*`, `infrastructure/storage/s3.py`, `tools/blue_green.sh`,
  `tests/unit/tools/test_blue_green_switch.py`, `uv.lock`,
  `.security/pip-audit-allowlist.txt` — не модифицированы.
- Cycle 1+2+3+4+5 atomic commits (15+) — не переписывал.

---

## 9. Compliance checklist

- [x] Minimal changes (mirror canonical pattern).
- [x] Docstring marker `cycle-6/D-AUDIT-604` присутствует.
- [x] Runtime не возвращает `None` silently (либо резолвит, либо `except + logger.warning`).
- [x] Test через DI provider без monkeypatch на `_resolve_tokenizer`.
- [x] Layer checker 175/0 (нет новых violations).
- [x] Docstring gate 0 missing.
- [x] Allowlist 27 (не увеличен).
- [x] uv.lock не тронут.
- [x] s3.py не тронут.
- [x] `except Exception` с `logger.warning` (не silent pass — соблюдает правило).
- [x] `gateway_adapter.py:128-129` не тронут.
- [x] Python 3.14+ syntax (`int | str` в docstring, `-> None`, no `Optional`).
- [x] Capability-checked фасад `get_pii_tokenizer_provider()` (DI pattern).
- [x] Russian-first docstring (не переводил).
- [x] `pytest.mark.asyncio` + `@pytest.mark.unit` через parent class collection.

---

*Cycle-6 D-AUDIT-604 fix complete. 1 atomic fix in `pii_unmask.py`, 1 regression
test, 16/16 tests PASS, layer checker / docstring gate / allowlist — все green.*