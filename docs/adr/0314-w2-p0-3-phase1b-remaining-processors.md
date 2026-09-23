# ADR-0314 — W2 P0-3 Phase 1B: 5 single-file processors migration (strangler_fig, data_lineage, plan_execute, reflection_loop, router_specialist)

* Статус: **Accepted** (2026-09-23, cycle 152).
* Связано с: MINIMAX W2 P0-3 (слияние процессоров); ADR-0313 (Phase 1A
  pilot для BatchProcessor); ADR-0084 (libraries > custom).
* Заменяет: 5 single-file processor'ов в `dsl/processors/` legacy ветке.

## Контекст

ADR-0313 (Phase 1A) мигрировал `BatchProcessor` как pilot. Cycle 152 Phase 1B
применяет тот же pattern к остальным 5 single-file процессорам:

| Legacy file | LOC | Canonical copy |
|---|---|---|
| `dsl/processors/strangler_fig.py` | 341 | `dsl/engine/processors/strangler_fig.py` |
| `dsl/processors/data_lineage.py` | 315 | `dsl/engine/processors/data_lineage.py` |
| `dsl/processors/plan_execute_processor.py` | 287 | `dsl/engine/processors/plan_execute_processor.py` |
| `dsl/processors/reflection_loop_processor.py` | 233 | `dsl/engine/processors/reflection_loop_processor.py` |
| `dsl/processors/router_specialist_processor.py` | 345 | `dsl/engine/processors/router_specialist_processor.py` |

**Total**: 1521 LOC консолидировано + 6 legacy shim файлов (после Phase 1A+1B).

## Решение

### Pattern (Phase 1A → Phase 1B evolution)

Phase 1A `BatchProcessor` shim использовал explicit `from canonical import X`.
Phase 1B улучшает pattern — **`__getattr__` lazy proxy** для проксирования
ЛЮБЫХ классов из canonical (mixin, enum, dataclass, etc.):

```python
import importlib as _importlib
import warnings as _warnings
from typing import Any as _Any

_warnings.warn(
    "src.backend.dsl.processors.{module} is deprecated; ...",
    DeprecationWarning, stacklevel=2,
)

_CANONICAL_MODULE = "src.backend.dsl.engine.processors.{module}"
_canonical = None

def __getattr__(name: str) -> _Any:
    global _canonical
    if _canonical is None:
        _canonical = _importlib.import_module(_CANONICAL_MODULE)
    return getattr(_canonical, name)

def __dir__() -> list[str]:
    if _canonical is None:
        _canonical = _importlib.import_module(_CANONICAL_MODULE)
    return dir(_canonical)
```

**Преимущества**:
* **Generic**: любой класс в canonical проксируется автоматически (RouteTarget,
  MigrationMixin, StranglerFigStats, StranglerFigRollback для strangler_fig).
* **Lazy import**: canonical импортируется только когда впервые нужен attribute.
* **Identity preserved**: `Legacy is Canonical` гарантирует что importers
  получают один класс (не fork).

### Изменения

1. **5 canonical copies** в `src/backend/dsl/engine/processors/<module>.py`
   (через `git cp` из legacy).
3. **5 legacy shims** в `src/backend/dsl/processors/<module>.py` с
   `__getattr__` lazy proxy + `DeprecationWarning`.
4. **`src/backend/dsl/processors/__init__.py`** обновлён — импортирует
   напрямую из canonical location (НЕ через legacy shim), чтобы
   downstream tooling, импортирующий :mod:`dsl.processors`, не получал
   DeprecationWarning.
5. **`src/backend/dsl/processors/batch_processor.py`** (Phase 1A) обновлён
   до того же `__getattr__` pattern для consistency.
6. **17 focused tests** в `test_w2_p0_3_phase1b_remaining_processors.py`:
   - TestStranglerFigShim (3): StranglerFigProcessor / RouteTarget / MigrationMixin identity.
   - TestDataLineageShim (3): DataLineageProcessor / LineageNode / LineageEvent identity.
   - TestPlanExecuteShim (4): PlanExecuteProcessor / PlanStep / PlanResult / PlanExecuteMixin identity.
   - TestReflectionLoopShim (3): ReflectionLoopProcessor / ReflectionResult / ReflectionLoopMixin identity.
   - TestRouterSpecialistShim (2): RouterSpecialistProcessor / SpecialistAgent identity.
   - TestDslProcessorsReExportHub (2): hub не эмитит warnings, SagaLRA legacy остаётся.

### Pre-existing tests regression check

```
uv run python -m pytest \
  tests/unit/dsl/processors/test_strangler_fig.py \
  tests/unit/dsl/processors/test_data_lineage.py \
  tests/unit/dsl/processors/test_plan_execute_processor.py \
  tests/unit/dsl/processors/test_reflection_loop_processor.py \
  tests/unit/dsl/processors/test_router_specialist_processor.py \
  tests/unit/dsl/processors/test_batch_processor.py \
  tests/unit/dsl/processors/test_w2_p0_3_batch_processor_migration.py \
  -q
  → 133 passed, 6 warnings (все DeprecationWarning — ожидаемые)
```

## Альтернативы (рассмотренные, отклонённые)

* **Mass-migrate + delete legacy в один commit**: отклонено — Phase 1B
  паттерн успешно проверен на BatchProcessor, лучше incremental.
* **Keep explicit re-export (Phase 1A pattern)**: отклонено — для
  файлов с 3-5 классами (RouteTarget, MigrationMixin, StranglerFigStats,
  etc.) explicit import + `__all__` поддерто хрупкий (при добавлении
  нового класса в canonical нужно обновлять shim). `__getattr__` proxy —
  self-maintaining.

## Последствия

**Плюсы**:

* 5 single-file processor'ов consolidated (1521 LOC) + generic shim pattern
  через `__getattr__` lazy proxy.
* Identity preserved для всех 5 processor'ов — importers не получают fork.
* Hub (`dsl/processors/__init__.py`) импортирует напрямую из canonical —
  не эмитит DeprecationWarning.
* Pattern готов для Phase 1C (event_store/ + idp_pipeline_processor/
  subpackages).

**Минусы / риски**:

* 6 DeprecationWarnings в логах pytest (по одному на каждый legacy shim).
  Mitigated: tooling может подавить `DeprecationWarning` для
  конкретного `module.*` pattern; telemetry signal остаётся.
* `__getattr__` lazy proxy требует Python ≥ 3.7 (PEP 562). Mitigated:
  проект requires Python ≥ 3.14.

## Verification (cycle 152)

```
compileall -q src/backend/dsl/processors/ src/backend/dsl/engine/processors/  → exit 0
uv run python -m pytest tests/unit/dsl/processors/test_w2_p0_3_phase1b_remaining_processors.py
  → 17 passed
uv run python -m pytest \
  tests/unit/dsl/processors/test_{strangler_fig,data_lineage,plan_execute_processor,
    reflection_loop_processor,router_specialist_processor,batch_processor}.py \
  tests/unit/dsl/processors/test_w2_p0_3_batch_processor_migration.py
  → 133 passed (pre-existing + Phase 1A regression-clean)
ruff check --select F401,F841,F811,E9                                       → All checks passed
```

## Связанные изменения (Phase 1B)

* **`src/backend/dsl/engine/processors/{strangler_fig,data_lineage,plan_execute_processor,
  reflection_loop_processor,router_specialist_processor}.py`** —
  canonical copies (5 файлов, 1521 LOC).
* **`src/backend/dsl/processors/{strangler_fig,data_lineage,plan_execute_processor,
  reflection_loop_processor,router_specialist_processor}.py`** —
  legacy shims с `__getattr__` lazy proxy (5 файлов).
* **`src/backend/dsl/processors/__init__.py`** — обновлён: direct canonical imports.
* **`src/backend/dsl/processors/batch_processor.py`** — Phase 1A shim unified с
  Phase 1B `__getattr__` pattern.
* **`tests/unit/dsl/processors/test_w2_p0_3_phase1b_remaining_processors.py`** —
  focused tests (17 тестов).
* **`docs/adr/0314-w2-p0-3-phase1b-remaining-processors.md`** — этот ADR.
* **`docs/adr/INDEX.md`** — ADR-0314 зарегистрирован (107 ADRs total).
* **`CHANGELOG.md`** + **`docs/roadmap/PROGRESS_LEDGER.md`** — синхронизированы.

Refs: MINIMAX W2 P0-3, ADR-0313 (Phase 1A pilot), ADR-0084, ADR-0314 (this),
cycle 152.