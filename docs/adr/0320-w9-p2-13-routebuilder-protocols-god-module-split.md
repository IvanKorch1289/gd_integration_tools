# ADR-0320 — W9 P2-13: `dsl/builders/base/_protocols.py` → package split (god-module decomposition)

* Статус: **Accepted** (cycle 153).
* Связано с: MINIMAX W9 (god-objects + честные docs); V15 forbidden pattern
  «God-modules (>500 LOC)»; ADR-0310 (.pyi drift regeneration); Cycle 244
  Protocol decomposition (Cycle 30 P4-#4 documentation contracts).

## Контекст

`src/backend/dsl/builders/base/_protocols.py` — 1094 LOC, 21 Protocol-классов +
1 helper (`_shares_prefix`). Файл документирует public API surface
RouteBuilder для будущей `CompositionRouteBuilder` (master prompt P4-#4
migration path: protocols → parallel impl → gradual caller migration →
RouteBuilder becomes thin wrapper).

**Проблема**:
- V15 forbidden pattern «God-modules (>500 LOC) — split на семейные модули».
- Физический размер файла 1094 LOC затрудняет навигацию по 21 cohesive
  протоколам, хотя логически они уже разделены.
- Top-1 god-module в `src/backend` (1094 LOC) — выше чем `core/di/providers/cache.py`
  (868), `core/privacy/delete_data_subject.py` (691), `services/ops/health.py` (609).

**Структура файла (21 protocol по доменам)**:

| # | Protocol | LOC | Домен |
|---|---|---|---|
| 1 | `_RouteProcessorSteps` | 5 | core (processor chain) |
| 2 | `_RouteCore` | 8 | core (identity+output) |
| 3 | `_RouteEntityCrudProtocol` | 82 | data (CRUD aliases) |
| 4 | `_RouteBatchDataProtocol` | 39 | data (batch+KV) |
| 5 | `_RouteControlFlowProtocol` | 39 | flow (control-flow) |
| 6 | `_RouteConcurrencyProtocol` | 34 | flow (concurrency) |
| 7 | `_RouteTimeResilienceProtocol` | 48 | flow (time/CB/HITL) |
| 8 | `_RouteDbProtocol` | 66 | data (SQL DML/DQL) |
| 9 | `_RoutePersistenceProtocol` | 39 | data (proc/file/S3/lookup) |
| 10 | `_RouteProxyProtocol` | 87 | integration (proxy/redirect/HTTP/GraphQL/LDAP/geo) |
| 11 | `_RouteSinkProtocol` | 114 | integration (sinks) |
| 12 | `_RouteSourceProtocol` | 79 | integration (sources) |
| 13 | `_RouteTemplateProtocol` | 43 | data (templates) |
| 14 | `_RouteIntegrationCoreProtocol` | 47 | integration (dispatch/invoke/util) |
| 15 | `_RouteAIOpsProtocol` | 39 | ai (LLM/RAG/inference) |
| 16 | `_RouteWorkflowOpsProtocol` | 66 | ai (Temporal orchestration) |
| 17 | `_RouteAgentProtocol` | 36 | ai (agent DSL) |
| 18 | `_RouteConverterProtocol` | 18 | support (format converters) |
| 19 | `_RouteContentProtocol` | 26 | support (EIP content ops) |
| 20 | `_RouteCollectionProtocol` | 38 | support (Groovy-style collections) |
| 21 | `_RouteSecurityProtocol` | 40 | support (auth/JWT/webhook signing) |
| 22 | `_RouteConfigProtocol` | 28 | support (with_*/set_header) |
| - | `_shares_prefix` (helper) | 10 | support (`__getattr__` diagnostic) |

**Анализ consumer'ов**:
- `base/__init__.py:352` — re-export всех 22 имён (back-compat).
- `tests/unit/cycle_31_s6_routebuilder.py` — 1 тест: импортирует через `base`
  + использует `inspect.getsource(_protocols)` (модульная ссылка).
- **0 runtime consumers**: протоколы используются ТОЛЬКО для type-checking
  (`@_runtime_checkable`) + IDE/docs (комментарий «документируют API surface»).
- **0 mixin'ов** не наследуются от `_Route*Protocol` (только от
  `_RouteBuilderProtocol` в `_protocol.py`, который остаётся как был).

## Решение

**Преобразовать `_protocols.py` (1094 LOC) → `_protocols/` package с 6 family
sub-modules + hub `__init__.py` для back-compat.**

### Семейства (cohesive groups)

| Submodule | LOC est. | Protocols |
|---|---|---|
| `_protocols/_core.py` | ~80 | `_RouteProcessorSteps`, `_RouteCore`, `_shares_prefix` |
| `_protocols/_data.py` | ~250 | `_RouteEntityCrudProtocol`, `_RouteBatchDataProtocol`, `_RouteDbProtocol`, `_RoutePersistenceProtocol`, `_RouteTemplateProtocol` |
| `_protocols/_flow.py` | ~180 | `_RouteControlFlowProtocol`, `_RouteConcurrencyProtocol`, `_RouteTimeResilienceProtocol` |
| `_protocols/_integration.py` | ~310 | `_RouteProxyProtocol`, `_RouteSinkProtocol`, `_RouteSourceProtocol`, `_RouteIntegrationCoreProtocol` |
| `_protocols/_ai.py` | ~150 | `_RouteAIOpsProtocol`, `_RouteWorkflowOpsProtocol`, `_RouteAgentProtocol` |
| `_protocols/_support.py` | ~110 | `_RouteConverterProtocol`, `_RouteContentProtocol`, `_RouteCollectionProtocol`, `_RouteSecurityProtocol`, `_RouteConfigProtocol` |

**Total: 6 файлов вместо 1, max ~310 LOC per submodule**.

### Back-compat strategy

1. **`_protocols/__init__.py`** re-экспортирует все 22 имени через
   `from ._core import (...)` и т.д. — back-compat сохраняется.
2. **`base/__init__.py`** остаётся без изменений (`from ... import _RouteCore, ...`)
   — это работает и для module, и для package.
3. **`inspect.getsource(_protocols)`** в cycle_31_s6_routebuilder.py работает
   потому что package `__init__.py` — файл с docstring + re-exports;
   assert проверяет что source содержит «Migration path» или «CompositionRouteBuilder»
   — сохраняем эти фразы в новом `__init__.py`.

### Что НЕ делаем

- **Не** трогаем `base/_protocol.py` (singular) — это utility protocol
  (48 LOC) для circular-import break, используется 10 mixin'ами через
  `_RouteBuilderProtocol`. Другая концепция, не god-module.
- **Не** рефакторим сами протоколы (сигнатуры, return types) — задокументированный
  contract, ломать = breaking change без ADR.
- **Не** удаляем `_shares_prefix` (helper используется в
  `__getattr__` diagnostic, cycle 204 Tier 3).

## Альтернативы (отклонённые)

1. **Keep as-is (1094 LOC)**: нарушает V15 forbidden pattern «god-modules».
2. **Split per-protocol (21 файлов)**: чрезмерная фрагментация, ~50 LOC файлы
   → шум в навигации, нет реального выигрыша.
3. **Co-locate protocols с mixins** (рядом с `batch.py`, `control_flow.py`):
   физически перетасовывает contracts с implementations, нарушает
   «протоколы = публичный contract documentation» separation.
4. **Удалить протоколы полностью** (CompositionRouteBuilder не планируется в
   ближайшие 2-3 sprint'а): отклонено — Protocol documentation всё равно
   полезна для IDE/help/type-checking (`isinstance` checks), и ADR cycle 244
   документирует что protocols оставлены как «future migration surface».

## Verification

```
compileall -q src/backend/dsl/builders/base/_protocols/                        → exit 0
python -c "from src.backend.dsl.builders.base import _protocols; print(_protocols.__file__)" → package path
python -c "from src.backend.dsl.builders.base import _RouteCore, _RouteDataProtocol" → importable
python -c "from src.backend.dsl.builders.base._protocols._data import _RouteDbProtocol" → importable
pytest tests/unit/cycle_31_s6_routebuilder.py -v                              → 5+ passed
ruff check --select F401,F841,F811,E9 src/backend/dsl/builders/base/_protocols/ → All checks passed
```

## Связанные изменения

* **`src/backend/dsl/builders/base/_protocols/`** — новый package:
  * `_core.py`, `_data.py`, `_flow.py`, `_integration.py`, `_ai.py`, `_support.py`,
    `__init__.py`.
* **`src/backend/dsl/builders/base/_protocols.py`** — удалён (заменён package).
* **`base/__init__.py`** — без изменений (back-compat через package import).
* **`tests/unit/cycle_31_s6_routebuilder.py`** — без изменений (работает
  через back-compat).
* **`docs/roadmap/PROGRESS_LEDGER.md`** — W9 P2-13 wave-memo.

Refs: MINIMAX W9, V15 forbidden pattern «god-modules», ADR-0310 (.pyi drift),
Cycle 244 (Protocol decomposition), Cycle 30 P4-#4 (CompositionRouteBuilder
migration path).
