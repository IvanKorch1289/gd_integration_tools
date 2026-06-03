# P1.0: AIGateway god-файл audit

**Audit date:** 2026-06-03 | **v9 P1 epic:** God-объекты | **Status:** audit only

## Метрики

| Метрика | Значение |
|---------|:--------:|
| File | `src/backend/core/ai/gateway.py` |
| Total LOC | **1091** |
| Classes | 4 (AIRequest, AIResponse, AIGateway, _AuditContext) |
| Public methods | 3 (`__init__`, `get_policy`, `invoke`) |
| Private methods | 21 (`_enforced_invoke`, `_legacy_invoke`, `_resolve_policy`, `_check_capability`, `_apply_input_sanitizers`, `_apply_input_guards`, `_render_prompt`, `_invoke_llm`, `_apply_output_guards`, `_apply_output_sanitizers`, `_audit_emit`, `_cost_track`, `_resolve_sanitizer`, `_resolve_llm_gateway`, `_language_from_policy`, `_extract_completion`, `_provider_from_model`, + 3 в `_AuditContext`) |
| External usages | **18+ файлов** |

## Структура файла (line ranges)

| Lines | Содержимое | LOC |
|-------|-----------|-----:|
| 1-81 | docstrings + imports | 81 |
| 83-114 | `AIRequest` dataclass | 32 |
| 115-141 | `AIResponse` dataclass | 27 |
| 143-220 | `AIGateway.__init__` | 78 |
| 222-249 | `get_policy` | 28 |
| 251-278 | `invoke` (entry point) | 28 |
| 280-365 | `_enforced_invoke` (9-step pipeline) | 86 |
| 367-380 | `_legacy_invoke` (scaffold) | 14 |
| 382-413 | `_resolve_policy` | 32 |
| 414-440 | `_check_capability` | 27 |
| 441-481 | `_apply_input_sanitizers` | 41 |
| 482-512 | `_apply_input_guards` | 31 |
| 513-588 | `_render_prompt` | 76 |
| 589-663 | `_invoke_llm` | 75 |
| 664-694 | `_apply_output_guards` | 31 |
| 695-743 | `_apply_output_sanitizers` | 49 |
| 744-800 | `_audit_emit` | 57 |
| 801-840 | `_cost_track` | 40 |
| 841-865 | `_resolve_sanitizer`, `_resolve_llm_gateway` | 25 |
| 866-879 | `_language_from_policy` | 14 |
| 880-931 | `_extract_completion` | 52 |
| 932-939 | `_provider_from_model` | 8 |
| 943-1067 | `_AuditContext` (dataclass + 3 methods) | 125 |
| 1069-1091 | `_emit_wrapper` (module-level) | 23 |

**Sum = 1091 LOC** (consistency check passed).

## Архитектурные наблюдения

### AIGateway — 9-step pipeline facade

Класс уже **логически разбит** на 9 шагов pipeline:
1. `get_policy` (pre-check, public)
2. `_resolve_policy` (step 1)
3. `_check_capability` (step 2)
4. `_apply_input_sanitizers` (step 3)
5. `_apply_input_guards` (step 4)
6. `_render_prompt` (step 5)
7. `_invoke_llm` (step 6)
8. `_apply_output_guards` (step 7)
9. `_apply_output_sanitizers` (step 8)
10. `_audit_emit` + `_cost_track` (step 9, audit+cost)

Каждый шаг уже отдельный метод (~30-80 LOC). **Но все методы внутри одного класса AIGateway**.

### `_AuditContext` — отдельная ответственность

`_AuditContext` (125 LOC) — dataclass с 3 методами, эмитит audit events. Не имеет прямого отношения к business logic gateway. **Логически отделима**.

## Split варианты (3 кандидата)

### Variant A: Package split (`core/ai/gateway/`)

```
core/ai/gateway/                          # NEW package
├── __init__.py                           # re-exports AIGateway, AIRequest, AIResponse
├── _facade.py                            # AIGateway class (thin facade, ~200 LOC)
├── _pipeline.py                          # 9 step functions as module-level (~600 LOC)
└── _audit.py                             # _AuditContext + _emit_wrapper (~150 LOC)
```

**Problem:** `core/ai/gateway.py` (модуль) → `core/ai/gateway/` (пакет) — Python **не позволяет** оба одновременно. Требует:
- Rename `core/ai/gateway.py` → `core/ai/aigateway.py` (имя освобождается)
- ИЛИ proxy module `core/ai/gateway.py` → `from .aigateway_impl import *`

**Pros:** Чистая структура, ~30% каждого файла.
**Cons:** Тот же package/module conflict что T1.3.1 features.py (отложен).

### Variant B: Parallel modules (no package)

```
core/ai/gateway.py                        # KEEP — AIGateway class (thin facade)
core/ai/gateway_steps.py                  # NEW — 9 step functions
core/ai/gateway_audit.py                  # NEW — _AuditContext + _emit_wrapper
```

**Pros:** Нет rename. Нет package conflict. Backward compat 100%.
**Cons:** Менее "чистая" структура. Шаги как module functions теряют доступ к `self._xxx` (нужен explicit DI).

### Variant C: Mixin pattern

```python
# core/ai/gateway.py
class AIGateway(GatewayStepsMixin, AuditContextMixin):  # composition
    def __init__(self): ...
```

**Pros:** No new files, code split through mixins.
**Cons:** Mixin complexity, интроспекция хуже, debugging сложнее.

## Рекомендация (как T1.3.1 features.py)

**Variant B (parallel modules)** — наименее рискованный. Нет package conflict. Backward compat. Прямой split по `_AuditContext` (125 LOC отдельный файл), 9 step methods — оставить в AIGateway (компактнее, чем module functions).

**Refined Variant B:**
1. Вынести `_AuditContext` (125 LOC) в `core/ai/gateway_audit.py` — импортируется в `gateway.py` для backward compat
2. Вынести `_emit_wrapper` (23 LOC) в `core/ai/gateway_audit.py` рядом
3. AIGateway class остаётся в `core/ai/gateway.py`, **теряет ~150 LOC** → 940 LOC

Это **первый split step** (T-P1.1). Дальнейшие шаги (split 9 steps на module functions) — T-P1.2+ если потребуется.

## Estimates (v9 P1 DoD)

| Метрика | Сейчас | После T-P1.1 | v9 target |
|---------|:------:|:-------------:|:---------:|
| gateway.py LOC | 1091 | 940 | <300 (P1 DoD) |
| god-файлов в core/ai | 1 | 1 | 0 |
| god-файлов в проекте | 166 | 165 | <50 |

T-P1.1 даёт 14% reduction, **далеко** от P1 DoD. Нужно 3-4 таких split'а для gateway.py И начать split других god-файлов.

## Следующие шаги

- **T-P1.1 (этот сеанс)**: Variant B step 1 — вынести `_AuditContext` в `gateway_audit.py`
- **T-P1.2**: Variant B step 2 — вынести step methods в `gateway_steps.py` (если нужно)
- **T-P1.3+**: Split других god-файлов: `core/integration.py` (2183), `core/providers.py` (1234), `core/lifecycle.py` (1100), `core/features.py` (2804, audit T1.1 done)

**Каждый split = 1 PR, ~150-300 LOC reduction.**

## Open questions

- Q1: Variant B ok, или юзер предпочитает Variant A (rename + package)?
- Q2: Сколько step methods выносить сразу? Все 9 или только логически-отделимые (audit, sanitizers, guards)?
- Q3: Параллельно с T-P1.1 — продолжать core/ai/gateway split, или переключиться на другой god-файл (core/integration.py 2183)?
