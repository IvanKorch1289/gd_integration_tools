# Cycle 5 — D-AUDIT-505 — Workflow Processors @processor registration

> **Дата:** 2026-08-07
> **HEAD:** `e5dcf18c` + локальные правки 4 файлов (1 LOC each)
> **Domain:** Workflow / DSL processors
> **Mode:** minimal-edit, additive only (docstring-markers + verify)
> **Reference:** `docs/audit/swarm-2026-08-06/cycle-4/phase-1/07-workflow.md` finding `DOMAIN-WF-P0-001`
> **Phase-3-plan:** N-1 (deferred to cycle 5+), компонент `4 @processor decorators`

---

## 1. TL;DR

| Метрика | Значение |
|---|---|
| Status | **✅ DONE — verification + marker applied** |
| Findings resolved | `workflow:DOMAIN-WF-P0-001` — уже **RESOLVED in HEAD** (B-1 fix, commit `4c3fc3b6`) |
| Diff stat (cycle-5 only) | **4 files changed, 4 insertions(+), 0 deletions(-)** |
| Files modified | `workflow_convert.py`, `workflow_subprocess.py`, `best_practices/claim_check.py`, `best_practices/continue_as_new.py` |
| Tests passing | **51/51 PASS** (0 regressions) |
| Docstring gate | **0 missing** (2277 files scanned) |
| Layer check | **0 new** (175/0 baseline preserved) |
| Forbidden files | **untouched** (uv.lock, .security/pip-audit-allowlist.txt, s3.py, blue_green.sh, test_blue_green_switch.py) |
| Registry verification | **4/4 present** in `ProcessorRegistry.list_specs()` (FQN `core:<name>`) |
| Pre-existing residuals | не трогали (`gateway_adapter.py:128-129`, `temporal_backend.py` modified by cycle-1+2+3) |

---

## 2. Scope / что реально сделано

### 2.1 Текущее состояние (verified в HEAD `e5dcf18c`)

Все 4 процессора **уже содержат** `@processor(...)` декоратор (применён в коммите `4c3fc3b6 feat(workflow): register 4 processors via @processor() decorator`, B-1 fix в cycle 1).

Подтверждено runtime-check (`importlib.iter_submodules` рекурсивно):

```
total registered: 76
workflow_convert: fqn=core:workflow_convert present=True
workflow_subprocess: fqn=core:workflow_subprocess present=True
workflow_continue_as_new: fqn=core:workflow_continue_as_new present=True
workflow_claim_check: fqn=core:workflow_claim_check present=True
```

Сравнение с audit (cycle-4 phase-1/07-workflow.md строки 132-140): audit использовал **не-рекурсивный** `pkgutil.iter_modules` и поэтому не зашёл в под-пакет `workflow/`. При рекурсивном обходе (cycle-5 verification) все 4 процессора присутствуют.

### 2.2 Минимальные правки cycle-5

Добавлен **docstring-marker** `cycle-5/D-AUDIT-505` в 4 файла — по 1 строке комментария непосредственно перед `@processor` декоратором. Это согласуется с PHASE-3-PLAN.md §0.3 (формат `# cycle-N/D-AUDIT-NNN — <краткое описание>`) и существующими примерами в `dsl/engine/processors/security.py` (cycle-2/D-AUDIT-03), `dsl/engine/processors/format_convert/data_formats.py` (cycle-4/D-AUDIT-103).

```python
# cycle-5/D-AUDIT-505 — register 4 workflow processors via @processor() decorator
@processor(
    "workflow_convert",  # (или workflow_subprocess / workflow_claim_check / workflow_continue_as_new)
    namespace="core",
    ...
)
```

### 2.3 Diff stat (cycle-5 only)

```diff
 src/backend/dsl/engine/processors/workflow/best_practices/claim_check.py     | 1 +
 src/backend/dsl/engine/processors/workflow/best_practices/continue_as_new.py | 1 +
 src/backend/dsl/engine/processors/workflow/workflow_convert.py               | 1 +
 src/backend/dsl/engine/processors/workflow/workflow_subprocess.py            | 1 +
 4 files changed, 4 insertions(+), 0 deletions(-)
```

---

## 3. Verification

### 3.1 ProcessorRegistry runtime-check

```bash
.venv/bin/python -c "
import importlib, pkgutil
def walk_pkg(pkg):
    if not hasattr(pkg, '__path__'): return
    for m in pkgutil.iter_modules(pkg.__path__):
        full = f'{pkg.__name__}.{m.name}'
        if m.ispkg:
            try: sub = importlib.import_module(full); walk_pkg(sub)
            except Exception: pass
        else:
            try: importlib.import_module(full)
            except Exception: pass
walk_pkg(importlib.import_module('src.backend.dsl.engine.processors'))
from src.backend.dsl.registry import get_processor_registry
specs = list(get_processor_registry().list_specs())
expected = ['workflow_convert', 'workflow_subprocess', 'workflow_continue_as_new', 'workflow_claim_check']
all_names = set(s.name for s in specs)
print('total:', len(specs), 'missing:', [n for n in expected if n not in all_names])
for n in expected:
    spec = get_processor_registry().get_by_short(n)
    print(f'  {n}: fqn=core:{n} present={spec is not None}')
"
```

Output (после правок):
```
total: 76 missing: []
  workflow_convert: fqn=core:workflow_convert present=True
  workflow_subprocess: fqn=core:workflow_subprocess present=True
  workflow_continue_as_new: fqn=core:workflow_continue_as_new present=True
  workflow_claim_check: fqn=core:workflow_claim_check present=True
```

Per-processor metadata (verified):
```
workflow_convert:        ns=core meta={'tier': 1, 'category': 'workflow'} caps=('workflow.convert.format',)
workflow_subprocess:      ns=core meta={'tier': 1, 'category': 'workflow'} caps=('workflow.subprocess.invoke',)
workflow_continue_as_new: ns=core meta={'tier': 1, 'category': 'workflow'} caps=('workflow.continue_as_new.request',)
workflow_claim_check:     ns=core meta={'tier': 1, 'category': 'workflow'} caps=('workflow.claim_check.store',)
```

### 3.2 Test suite (.venv/bin/python)

```bash
.venv/bin/python -m pytest \
  tests/unit/dsl/engine/processors/workflow/ \
  tests/workflow/ \
  tests/unit/dsl/engine/processors/test_sub_workflow.py \
  tests/unit/dsl/engine/processors/test_cancel_workflow.py \
  --no-header -q
```

```
51 passed, 8 warnings in 3.89s
```

Test breakdown:
- `tests/unit/dsl/engine/processors/workflow/test_processor_registry_integration.py`: **4 tests** (per-processor registration assert)
- `tests/unit/dsl/engine/processors/workflow/test_workflow_subprocess.py`: **8 tests**
- `tests/unit/dsl/engine/processors/workflow/best_practices/`: **19 tests**
- `tests/workflow/test_state_persistence.py`: **8 tests**
- `tests/unit/dsl/engine/processors/test_sub_workflow.py`: **7 tests**
- `tests/unit/dsl/engine/processors/test_cancel_workflow.py`: **5 tests**

Pre-existing failures в `tests/unit/infrastructure/workflow/test_temporal_namespace_mismatch.py` (ImportError) и `tests/unit/infrastructure/workflow/test_lite_temporal_backend.py` — **НЕ связаны** с моими правками. Подтверждено через `git stash` + повторный прогон: падения воспроизводятся без моих изменений. Это pre-existing residuals из N-1 / temporal-backend-цикл (вне scope этой задачи).

### 3.3 Docstring gate

```bash
.venv/bin/python tools/check_docstrings.py
```

```
Total: 0 missing docstrings in 0 files
Files scanned: 2277
```

### 3.4 Layer checker

```bash
.venv/bin/python tools/check_layers.py --root src
```

```
Нарушений: 0 новых  (файлов: 2277; baseline: 175 legacy)
```

Layer baseline **175/0 сохранён**.

### 3.5 Forbidden files check

| File | Status |
|---|---|
| `uv.lock` | **НЕ изменён** (pre-existing diff от cycle-1+2+3 — 17 lines из чужого коммита; в моих 4 правках 0 строк uv.lock) |
| `.security/pip-audit-allowlist.txt` | **НЕ изменён** (count = 27 active CVE-IDs, baseline сохранён) |
| `src/backend/infrastructure/storage/s3.py` | **НЕ изменён** |
| `tools/blue_green.sh` | **НЕ изменён** |
| `tests/unit/tools/test_blue_green_switch.py` | **НЕ изменён** |
| `src/backend/services/ai/gateway_adapter.py:128-129` | **НЕ изменён** (pre-existing residual, явно запрещено) |

---

## 4. Что НЕ сделано (явно вне scope)

| Компонент N-1 | Статус | Причина |
|---|---|---|
| `TemporalWorkerPool` instantiate + Typer CLI | **DEFERRED** (cycle 5+) | HIGH RISK — требует ADR + `uv sync --extra workflow` + реальный Temporal-кластер; PHASE-3-PLAN.md §7 N-1 explicit defer |
| `ActivityBridge.decorate()` wire-up | **DEFERRED** | Same as above (N-1 sub-task) |
| `cancel_workflow` fail-CLOSED + dsl→services layer violation | **DEFERRED** | Out of scope (DOMAIN-WF-P0-003); требует отдельного цикла |
| Worker-handlers (subprocess/claim_check/continue_as_new) в Temporal-кластере | **DEFERRED** | Зависит от TemporalWorkerPool runtime |

Per AGENTS.md и user prompt: «Cycle 1+2+3+4 правки НЕ переписывать». Моя задача — **только** docstring-marker + verify, без изменения поведения.

---

## 5. Cycle-1+2+3+4 правки (НЕ переписывал)

| ID | Commit | Файл | Статус |
|---|---|---|---|
| B-1 (cycle 1) | `4c3fc3b6` | `workflow_convert.py`, `workflow_subprocess.py`, `claim_check.py`, `continue_as_new.py` (4 файла) | **Сохранён** (только marker добавлен) |
| D-AUDIT-11 (cycle 1) | `d9837dc9` | `core/config/features/workflow.py` | **Не трогал** |
| B-15 (cycle 37) | `bddfc8e3` | `dsl/workflow/compiler/*` | **Не трогал** |
| S193 TenantFacade kwargs | T-08 RESIDUAL | `services/tenancy/facade.py` | **Не трогал** (per user prompt: cycle 1+2+3+4 не переписывать) |

---

## 6. Команды выполненные

```bash
# Verification (before edits)
.venv/bin/python -c "<recursive walk + list_specs>"
# → 76 total, all 4 workflow processors present

# Edits
# 4 × Edit (1 line each) — добавлен cycle-5/D-AUDIT-505 marker

# Verification (after edits)
.venv/bin/python -m pytest tests/unit/dsl/engine/processors/workflow/ \
  tests/workflow/ tests/unit/dsl/engine/processors/test_sub_workflow.py \
  tests/unit/dsl/engine/processors/test_cancel_workflow.py --no-header -q
# → 51 passed

.venv/bin/python tools/check_docstrings.py
# → 0 missing, 2277 files scanned

.venv/bin/python tools/check_layers.py --root src
# → 0 new violations, 175/0 baseline

.venv/bin/python -c "<registry verification>"
# → 4/4 present in ProcessorRegistry.list_specs()
```

---

## 7. Готовность по finding

| Finding | До | После |
|---|---|---|
| `workflow:DOMAIN-WF-P0-001` (4 processors без `@processor`) | RESOLVED in HEAD (B-1 cycle 1, commit `4c3fc3b6`) | **RESOLVED + audit-marker** (cycle-5/D-AUDIT-505 applied to all 4 files; runtime verified) |
| `workflow:DOMAIN-WF-P0-002` (TemporalWorkerPool uninstantiated) | RESIDUAL | RESIDUAL (deferred to cycle 5+ per PHASE-3-PLAN N-1) |
| `workflow:DOMAIN-WF-P0-003` (cancel_workflow fail-OPEN) | RESIDUAL | RESIDUAL (out of scope this cycle) |
| `workflow:DOMAIN-WF-P0-004` (worker-handlers unreached) | RESIDUAL | RESIDUAL (depends on P0-002 wire-up) |

**Status:** T-C5-05-WORKFLOW-PROCESSORS ✅ DONE — 1 из 4 P0 finding'ов workflow-домена получил cycle-5 audit-trail. Остальные 3 P0 — вне scope этой задачи (требуют ADR + Temporal cluster).

---

## 8. Резюме

- **Объём правок:** 4 файла × 1 LOC = 4 строки (только docstring-маркеры).
- **Поведение:** zero behavioral change. Декораторы уже были в HEAD (B-1 fix cycle 1); правки чисто audit/traceability.
- **Тесты:** 51/51 PASS (включая `test_processor_registry_integration.py` с per-processor assert).
- **Gates:** docstring 0 missing, layer 175/0, allowlist 27 (untouched).
- **Forbidden files:** все 5 нетронуты.
- **Registry:** все 4 процессора присутствуют (FQN `core:<name>`).

**Конечный verdict:** cycle-5 DOMAIN-WF-P0-001 = **VERIFIED + TRACEABLE**. Audit-trail `cycle-5/D-AUDIT-505` в каждом из 4 файлов обеспечивает forward-references при следующих ревизиях кода.
