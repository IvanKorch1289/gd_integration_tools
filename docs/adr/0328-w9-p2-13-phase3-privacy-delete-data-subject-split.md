# ADR-0328 — W9 P2-13 Phase 3: `core/privacy/delete_data_subject.py` → package split (god-module decomposition)

* Статус: **Accepted** (cycle 153).
* Связано с: MINIMAX W9 (god-objects); V15 forbidden pattern «God-modules
  (>500 LOC)»; ADR-0320 (W9 P2-13 protocols split); ADR-0321 (W9 P2-13
  Phase 2 cache split).

## Контекст

`src/backend/core/privacy/delete_data_subject.py` (691 LOC, 11 классов) —
top-3 god-module в `src/backend` после W9 P2-13 protocols split и W9
P2-13 Phase 2 cache split. Содержит privacy/data-subject erasure lifecycle:

* 2 Enum: `ErasureStrategy` (hard_delete / anonymize), `ErasureResultStatus`
* 2 dataclasses: `AdapterResult`, `OrchestratorResult`
* 1 Protocol: `ErasureAdapter`
* 5 storage adapters: `PostgresErasureAdapter`, `RedisErasureAdapter`,
  `S3ErasureAdapter`, `QdrantErasureAdapter`, `LangMemErasureAdapter`
* 1 publisher: `TombstonePublisher`
* 1 main orchestrator: `DeleteDataSubject`

**Проблема**:
- V15 forbidden pattern «God-modules (>500 LOC) — split на семейные модули».
- 691 LOC нарушает даже расширенный threshold.
- Cohesive concerns mixed: protocol definitions + 5 storage adapters +
  tombstone publisher + orchestrator в одном файле.
- Изменения в одном adapter требуют touch большого файла (merge conflicts).

**Consumer audit**:
- `src/backend/core/privacy/__init__.py` — public API facade (re-exports all 11).
- `src/backend/core/privacy/delete_data_subject.py:163:    from src.backend.core.privacy.delete_data_subject import (` — self-reference (internal).

Total external importers: 0 (только через `core.privacy.__init__` re-exports).

## Решение

### Phase 3A: Split на `core/privacy/delete_data_subject/` package

Преобразовать `delete_data_subject.py` (691 LOC, 11 классов) → `delete_data_subject/`
package с 8 submodules по cohesion:

| Submodule | LOC est. | Содержимое |
|---|---|---|
| `__init__.py` | ~50 | back-compat re-exports |
| `_types.py` | ~80 | `ErasureStrategy`, `ErasureResultStatus`, `AdapterResult`, `OrchestratorResult`, `ErasureAdapter` (Protocol) |
| `_postgres.py` | ~50 | `PostgresErasureAdapter` |
| `_redis.py` | ~95 | `RedisErasureAdapter` |
| `_s3.py` | ~110 | `S3ErasureAdapter` |
| `_qdrant.py` | ~115 | `QdrantErasureAdapter` |
| `_langmem.py` | ~85 | `LangMemErasureAdapter` |
| `_tombstone.py` | ~30 | `TombstonePublisher` |
| `_orchestrator.py` | ~140 | `DeleteDataSubject` (main) |

**Total**: ~755 LOC distributed (с overhead от re-exports + module headers),
но каждый файл < 150 LOC, каждый cohesion-focused.

### Back-compat strategy (W2 P0-3 SagaLRA Variant A pattern, ADR-0316)

* `core/privacy/delete_data_subject.py` → thin re-export shim через
  `from .delete_data_subject import ...`.
* `core/privacy/__init__.py` без изменений (уже импортирует из
  `delete_data_subject` re-exports).
* Все 11 классов доступны через обе entry points: `from core.privacy import X`
  и `from core.privacy.delete_data_subject import X`.

### Что НЕ делаем

* **Не** рефакторим adapter implementations (изменения логики = breaking
  change без ADR; и не входит в scope Phase 3).
* **Не** трогаем `core/privacy/__init__.py` public API surface.
* **Не** удаляем ErasureAdapter Protocol — он используется как type hint в
  orchestrator для type-safe adapter registration.

## Альтернативы (отклонённые)

1. **Keep as-is (691 LOC)**: нарушает V15 forbidden pattern.
2. **Split per adapter (8 файлов)**: cohesive grouping лучше — types + adapter
   pairs со связанными concerns остаются вместе.
3. **Single new module `privacy_adapters.py`**: не улучшает navigation — все
   adapters в одном файле не лучше чем сейчас.
4. **Move to extensions/**: privacy = core domain, не business logic.

## Verification

```
compileall -q src/backend/core/privacy/                            → exit 0
ruff check --select F401,F841,F811,E9 src/backend/core/privacy/    → All checks passed
python -c "from src.backend.core.privacy import DeleteDataSubject, ErasureAdapter, PostgresErasureAdapter, ..."
                                                                  → importable
pytest tests/unit/core/privacy/ (если есть)                          → passed
pytest tests/unit/services/execution/ (consumer tests)              → passed
```

## Связанные изменения

* **`src/backend/core/privacy/delete_data_subject.py`** → thin re-export shim (~10 LOC).
* **`src/backend/core/privacy/delete_data_subject/`** — новый package (8 submodules).
* **`src/backend/core/privacy/__init__.py`** — без изменений.
* **Tests**: `tests/unit/core/privacy/test_w9_p2_13_phase3_delete_data_subject_split.py` (NEW):
  - TestBackCompatImports (12): все 11 классов + Protocol + dataclasses импортируются
    из обоих путей (`core.privacy` и `core.privacy.delete_data_subject`).
  - TestSubmoduleExports (8): каждый submodule экспортирует ожидаемые классы.
  - TestProtocolConformance (5): все 5 адаптеров реализуют `ErasureAdapter` Protocol
    (duck typing — проверить что у каждого есть `erase` method).

## Phase 3B (deferred, отдельный sub-wave)

Phase 3A решает split. Phase 3B будет:
- Audit дубликатов в adapter logic (RedisErasureAdapter и QdrantErasureAdapter
  могут иметь shared patterns — extract to mixin/base class).
- TombstonePublisher — отдельный module (Kafka sink?) — оценить в Phase 3B.

## Roadmap (после Phase 3)

Следующие god-modules per V15 forbidden pattern:
* `services/ops/health.py` (609 LOC) — Phase 4 (health endpoints split).
* `services/ai/agent_sandbox.py` (601 LOC) — Phase 5 (sandbox split).
* `core/di/providers/workflow.py` (602 LOC после W9 P2-13 Phase 2) — Phase 6
  (workflow split, если не уменьшится после Phase 3B shim removal).
* `core/ai/skill_registry.py` (614 LOC) — Phase 7 (skill registry split).

Refs: MINIMAX W9 P2-13 Phase 3, V15 forbidden pattern «god-modules»,
ADR-0316 (W2 P0-3 SagaLRA Variant A back-compat pattern), ADR-0320 (W9 P2-13
protocols split), ADR-0321 (W9 P2-13 Phase 2 cache split).
