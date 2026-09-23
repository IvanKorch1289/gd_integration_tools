# ADR-0313 — W2 P0-3 Phase 1A: BatchProcessor migration pilot (single-file processor consolidation)

* Статус: **Accepted** (2026-09-23, cycle 152).
* Связано с: MINIMAX W2 P0-3 (слияние процессоров из `dsl/processors/` в
  `dsl/engine/processors/`); ADR-0084 (libraries > custom);
  W2 prerequisite (ADR-0308 SagaLRA deadline integration re-apply).
* Заменяет: дублирование single-file processor'ов в двух ветках.

## Контекст

MINIMAX baseline зафиксировал: **26 файлов** в `src/backend/dsl/processors/`
(legacy ветка) vs **318 файлов** в `src/backend/dsl/engine/processors/`
(current canonical ветка). Это нарушает архитектурный принцип «один способ
сделать X» — для каждого processor было две параллельные реализации.

Cycle 152 W2 prerequisite (ADR-0308) закрыл Critical Finding для SagaLRA
(cycle 135 deadline integration был только на legacy; production
использует current). Остаётся сделать реальное слияние.

**Cycle 152 recon** (`src/backend/dsl/processors/`):

| Subpackage | Файлов | LOC | Тип |
|---|---|---|---|
| `batch_processor.py` | 1 | 153 | single-file ✓ pilot |
| `data_lineage.py` | 1 | 315 | single-file |
| `plan_execute_processor.py` | 1 | 287 | single-file |
| `strangler_fig.py` | 1 | 341 | single-file |
| `reflection_loop_processor.py` | 1 | 233 | single-file |
| `router_specialist_processor.py` | 1 | ? | single-file |
| `event_store/` | 6 | ~600 | subpackage |
| `saga_lra_processor/` | 7 | ~1100 | subpackage (mixin) — **другая реализация**, не дубликат |
| `idp_pipeline_processor/` | 7 | ~1200 | subpackage |

**External importers** (cycle 152):
- 10+ тестов используют legacy paths (`tests/unit/dsl/processors/test_*.py`)
- `dsl/processors/__init__.py` — re-export hub для `BatchProcessor`,
  `PlanExecuteProcessor`, `SagaLRAProcessor`

## Решение

### Phase 1A (этот commit): BatchProcessor pilot

Самый простой single-file processor выбран для pilot:

1. **Canonical-копия** в `src/backend/dsl/engine/processors/batch_processor.py`
   (153 LOC, `git cp` из legacy). Импорты внутри уже указывают на
   `dsl.engine.processors.base` — никаких path-изменений не нужно.

2. **Legacy → re-export shim** в `src/backend/dsl/processors/batch_processor.py`
   (37 LOC, с `DeprecationWarning` на импорт модуля). Stacklevel=2.

3. **`dsl/processors/__init__.py`** — продолжает re-export через
   `from src.backend.dsl.processors.batch_processor import BatchProcessor`.
   Поскольку legacy теперь shim, transitive users получат DeprecationWarning.

4. **Тесты**: `test_w2_p0_3_batch_processor_migration.py` (4 теста):
   - `TestBatchProcessorIdentity` (2): legacy/current → один класс.
   - `TestLegacyDeprecationWarning` (1): legacy путь emits `DeprecationWarning`
     с ссылкой на ADR-0313.
   - `TestBatchProcessorInstantiation` (1): class metadata доступны через
     legacy path.

### Phase 1B (отдельные коммиты, следующие waves)

По аналогичному pattern:

* **strangler_fig.py** (341 LOC) → migrate.
* **data_lineage.py** (315 LOC) → migrate.
* **plan_execute_processor.py** (287 LOC) → migrate.
* **reflection_loop_processor.py** (233 LOC) → migrate.
* **router_specialist_processor.py** → migrate.
* **event_store/** subpackage → migrate (6 файлов).
* **idp_pipeline_processor/** subpackage → migrate (7 файлов).

Каждый = atomic commit с focused tests + re-export shim update.

### Phase 2 (SagaLRA — отдельная ветка решений)

**SagaLRA — другая реализация**, не дубликат. Legacy использует mixin-based
архитектуру (CoreMixin + LifecycleMixin + SerializationMixin +
ExecutionMixin), current — single file (BaseProcessor). Решение требует
отдельного ADR:

* **Вариант A**: Migrate legacy SagaLRA в `dsl/engine/processors/saga_lra/`
  subpackage (4 mixin files + state). Pros: сохраняет legacy extension
  points. Cons: дубликат current saga_lra.py.
* **Вариант B**: Deprecate legacy SagaLRA, force-migrate importers к
  current saga_lra.py (которая уже имеет deadline integration per
  ADR-0308). Pros: один canonical. Cons: breaking change для legacy
  extensions.

Решение — отдельный wave после Phase 1B completion.

### Phase 3 (Removal)

После cycle 156 (~1 release) — telemetry audit + удаление legacy shim'ов.

## Альтернативы (рассмотренные, отклонённые)

* **Mass-migrate все 26 файлов в один commit**: отклонено — большой diff,
  сложно ревью, риск regression.
* **Удалить legacy сразу (без shim)**: отклонено — ломает public contract,
  ~10 тестов + downstream tooling.
* **Использовать `importlib.util.spec_from_file_location` для runtime shim**:
  отклонено — overengineering для простой re-export задачи.

## Последствия

**Плюсы**:

* Pilot pattern проверен на простом processor'е — повторяемость для
  остальных 5 single-file + 3 subpackage.
* `BatchProcessor` теперь живёт в canonical location
  (`dsl/engine/processors/`). Downstream tooling получает telemetry signal
  (DeprecationWarning) для migration.
* Identity preserved: `LegacyBatchProcessor is CurrentBatchProcessor`
  гарантирует что importers не получают двух разных классов.

**Минусы / риски**:

* DeprecationWarning может шуметь в проде для ~10 importers. Mitigated:
  removal только после telemetry audit (cycle 156+).
* Phase 1B требует 6+ atomic commits (механический pattern, низкий risk).

## Verification

```
python3.14 -m compileall -q src/backend/dsl/processors/batch_processor.py
  → exit 0
python3.14 -m compileall -q src/backend/dsl/engine/processors/batch_processor.py
  → exit 0

python3.14 -c "from src.backend.dsl.processors.batch_processor import BatchProcessor as A; \
              from src.backend.dsl.engine.processors.batch_processor import BatchProcessor as B; \
              assert A is B; print('Identity OK')"
  → Identity OK

uv run python -m pytest tests/unit/dsl/processors/test_w2_p0_3_batch_processor_migration.py
  → 4 passed
uv run python -m pytest tests/unit/dsl/processors/test_batch_processor.py
  → 13 passed (pre-existing, regression-clean)

compileall -q src/ extensions/ scripts/ tools/ tests/  → exit 0
ruff check --select F401,F841,F811,E9                   → All checks passed!
```

## Связанные изменения (Phase 1A)

* **`src/backend/dsl/engine/processors/batch_processor.py`** — canonical
  копия (153 LOC).
* **`src/backend/dsl/processors/batch_processor.py`** — re-export shim
  (37 LOC, с DeprecationWarning).
* **`tests/unit/dsl/processors/test_w2_p0_3_batch_processor_migration.py`** —
  focused tests (4 теста).
* **`docs/adr/0313-w2-p0-3-batch-processor-migration-pilot.md`** — этот ADR.
* **`docs/adr/INDEX.md`** — ADR-0313 зарегистрирован (106 ADRs total).
* **`CHANGELOG.md`** + **`docs/roadmap/PROGRESS_LEDGER.md`** — синхронизированы.

Refs: MINIMAX W2 P0-3 (consolidation), ADR-0084 (libraries > custom),
ADR-0308 (SagaLRA Critical Finding fix), ADR-0313 (this), cycle 152.