# ADR-0315 — W2 P0-3 Phase 1C: event_store + idp_pipeline_processor subpackages migration

* Статус: **Accepted** (2026-09-23, cycle 152).
* Связано с: MINIMAX W2 P0-3 (слияние процессоров); ADR-0313 (Phase 1A),
  ADR-0314 (Phase 1B).
* Заменяет: 2 subpackages в `dsl/processors/` legacy ветке.

## Контекст

ADR-0313 (Phase 1A) + ADR-0314 (Phase 1B) мигрировали **6 single-file
processor'ов** (BatchProcessor + 5 остальных). Cycle 152 Phase 1C
применяет тот же pattern к **2 subpackages**:

| Legacy subpackage | Файлов | LOC | Архитектура |
|---|---|---|---|
| `dsl/processors/event_store/` | 6 | 566 | flat (CQRSMixin, EventStore, EventStoreProcessor) |
| `dsl/processors/idp_pipeline_processor/` | 8 | 666 | mixin-based (PipelineMixin, RoutingMixin, etc.) |

**Total**: 1232 LOC консолидировано + 2 legacy subpackage shims.

## Решение

### Subpackage migration pattern

Phase 1B pattern (`__getattr__` lazy proxy) применён к **subpackage
`__init__.py`** — позволяет проксировать любые классы/data-классы/
функции из canonical subpackage без дублирования `__all__`:

```python
# src/backend/dsl/processors/event_store/__init__.py (legacy shim)
import importlib as _importlib
import warnings as _warnings
from typing import Any as _Any

_warnings.warn(
    "src.backend.dsl.processors.event_store is deprecated; ...",
    DeprecationWarning, stacklevel=2,
)

_CANONICAL_MODULE = "src.backend.dsl.engine.processors.event_store"
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

### Изменения

1. **2 canonical subpackages** созданы в
   `src/backend/dsl/engine/processors/{event_store,idp_pipeline_processor}/`.
   - Файлы скопированы через `cp` (6 + 8 = 14 файлов).
   - **Imports внутри subpackages обновлены** (12 файлов): все
     `from src.backend.dsl.processors.X import` → `from src.backend.dsl.engine.processors.X import`.

2. **2 legacy subpackage shims** созданы в
   `src/backend/dsl/processors/{event_store,idp_pipeline_processor}/__init__.py`
   с `__getattr__` lazy proxy + DeprecationWarning.

3. **`src/backend/dsl/processors/__init__.py`** обновлён — добавляет
   13 новых re-exports из canonical subpackages:
   - `EventStore, InMemoryEventStore, EventStoreProcessor, CommandBus,
     QueryBus, Projection, CQRSMixin, Event, EventStream,
     get_event_store, set_event_store, reset_event_store` (event_store).
   - `IDPPipelineProcessor, classify_document, extract_fields,
     validate_result` (idp_pipeline_processor).

4. **16 focused tests** в `test_w2_p0_3_phase1c_subpackages.py`:
   - TestEventStoreShim (10): EventStore / InMemoryEventStore /
     EventStoreProcessor / CommandBus / QueryBus / Projection / CQRSMixin /
     Event / EventStream / 3 helper functions identity.
   - TestIDPPipelineShim (4): IDPPipelineProcessor / classify_document /
     extract_fields / validate_result identity.
   - TestDslProcessorsReExportHubPhase1C (2): hub imports работают без
     DeprecationWarnings, helpers доступны.

### Pre-existing tests regression check

```
uv run python -m pytest \
  tests/unit/dsl/processors/test_event_store.py \
  tests/unit/dsl/processors/test_idp_pipeline_processor.py \
  -q
  → 58 passed, 2 warnings (DeprecationWarning на legacy shim import — expected)
```

## Альтернативы (рассмотренные, отклонённые)

* **Mass-migrate all subpackages в один commit**: отклонено — Phase 1B/1C
  pattern proven, incremental лучше для review.
* **Re-export только top-level classes** (Phase 1A explicit style):
  отклонено — `event_store/__init__.py` экспортирует 12 имён;
  обновлять explicit list при каждом добавлении класса в canonical
  хрупко. `__getattr__` self-maintaining.
* **Использовать `__getattr__` для subpackage и explicit re-export для
  flat файлов**: отклонено — единообразие важнее. Применяем тот же
  pattern везде.

## Последствия

**Плюсы**:

* 2 subpackages consolidated (1232 LOC) + generic `__getattr__` pattern
  работает на subpackage уровне.
* Все классы/data-классы/функции (12 в event_store + 4 в idp_pipeline)
  проксируются автоматически.
* Hub импортирует напрямую из canonical — no DeprecationWarning при
  импорте :mod:`dsl.processors`.

**Минусы / риски**:

* 8 DeprecationWarnings в pytest output (6 single-file Phase 1B + 2 subpackage
  Phase 1C). Mitigated: tooling может подавить по `module.*` pattern.

## Verification (cycle 152)

```
compileall -q src/backend/dsl/processors/ src/backend/dsl/engine/processors/event_store/ \
                   src/backend/dsl/engine/processors/idp_pipeline_processor/  → exit 0

uv run python -m pytest tests/unit/dsl/processors/test_w2_p0_3_phase1c_subpackages.py
  → 16 passed
uv run python -m pytest tests/unit/dsl/processors/test_event_store.py \
                       tests/unit/dsl/processors/test_idp_pipeline_processor.py
  → 58 passed (pre-existing, regression-clean)

ruff check --select F401,F841,F811,E9                                       → All checks passed
```

## Связанные изменения (Phase 1C)

* **`src/backend/dsl/engine/processors/event_store/`** — canonical subpackage (6 файлов, 566 LOC).
* **`src/backend/dsl/engine/processors/idp_pipeline_processor/`** — canonical subpackage (8 файлов, 666 LOC).
* **`src/backend/dsl/processors/event_store/__init__.py`** — legacy shim с `__getattr__` lazy proxy.
* **`src/backend/dsl/processors/idp_pipeline_processor/__init__.py`** — legacy shim с `__getattr__` lazy proxy.
* **`src/backend/dsl/processors/__init__.py`** — обновлён: +13 re-exports.
* **`tests/unit/dsl/processors/test_w2_p0_3_phase1c_subpackages.py`** — 16 focused tests.
* **`docs/adr/0315-w2-p0-3-phase1c-event-store-idp-pipeline-subpackages.md`** — этот ADR.
* **`docs/adr/INDEX.md`** — ADR-0315 зарегистрирован (108 ADRs total).
* **`CHANGELOG.md`** + **`docs/roadmap/PROGRESS_LEDGER.md`** — синхронизированы.

Refs: MINIMAX W2 P0-3, ADR-0313 (Phase 1A), ADR-0314 (Phase 1B), ADR-0315,
cycle 152.