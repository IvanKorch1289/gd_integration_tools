# ADR-0307 — W3 P0-4: shim inventory + classification (MINIMAX Phase 1)

* Статус: **Accepted** (2026-09-23, cycle 152).
* Связано с: MINIMAX W3 (P0-4, P0-5); ADR-0084 (библиотеки > кастом);
  ADR-0249 (capability-checked facades).
* Фаза: Phase 1 (inventory + ADR + safe-DEPRECATE кандидаты).

## Контекст

MINIMAX baseline зафиксировал **65 файлов с `__getattr__`** (в src, без
pycache), из них **15 явных backward-compat shims** (с явной маркировкой
"Backward-compat" в docstring). Плюс **7 Sprint 224 lazy proxies** (без
явной маркировки, но по паттерну "Sprint 224 refactor: convert direct
re-export to __getattr__-based lazy proxy").

Sprint 224 (август 2026) провёл рефакторинг: заменил прямые re-exports
на `__getattr__`-based lazy proxies для:

* Избежания circular imports.
* Ускорения startup (lazy load infrastructure).
* Обхода layer-violations (`services → infrastructure` через
  `core.api.services.X` facade).

Эти шимы — **ОБОСНОВАННЫЕ**, не legacy cruft. Удалять нельзя.

**Backward-compat shims** (15 файлов) — другая история. Каждый появился
после god-file decomp (S56-S65), когда canonical API переехал в
sub-module, а старый import path оставили как backward-compat alias.
Вопрос: какие из них ещё нужны, какие можно пометить как deprecated?

## Решение Phase 1

### Inventory + classification table

Сделан полный аудит 15 backward-compat shim файлов (см. секцию «Inventory»
ниже). Каждый классифицирован по 4-критериальной шкале:

1. **`sprint224-lazy-proxy`** — Sprint 224 refactor (lazy proxy для
   layer-violation avoidance / lazy load). **НЕ ТРОГАТЬ**.
2. **`backward-compat-shim`** — сохраняет старый import path. **Оставить
   до audit импортёров** (есть downstream tooling).
3. **`deprecation-candidate`** — docstring явно говорит deprecated +
   canonical API exists. **Safe для DeprecationWarning**.
4. **`stable-facade`** — current canonical API, несмотря на `__getattr__`.
   **НЕ трогать**.
5. **`analysis-needed`** — unclear, нужно углублённое исследование.

### Phase 1A (этот commit): `core/facades.py` deprecation

**`src/backend/core/facades.py`** — backward-compat shim с явной маркировкой:

* Docstring: "NEVER use this module in new code. Use
  `src.backend.core.api` instead."
* 1 external importer (verified через `rg -l`).
* Canonical `src/backend.core.api` существует.
* **Action**: добавлен `warnings.warn(DeprecationWarning, stacklevel=2)`
  на import модуля.

**Verification**:

```
python3.14 -W error::DeprecationWarning -c "import src.backend.core.facades"
→ DeprecationWarning: src.backend.core.facades is deprecated;
  use src.backend.core.api instead.

python3.14 -m compileall -q src/backend/core/facades.py → exit 0
```

### Phase 1B (следующие коммиты): остальные кандидаты

Список кандидатов для Phase 1B (после telemetry / audit импортёров):

| Кандидат | Класс | Импортёры | Action |
|---|---|---|---|
| `core/di/providers/infrastructure_facade.py` | already-deprecated | 1 | УЖЕ имеет warning, ничего |
| `services/io/external_database/__init__.py` | backward-compat | 1 | Audit + DEPRECATE в Phase 1B |
| `dsl/engine/processors/eip/reliability/_legacy.py` | misleading-name | 5 | **Rename** в Phase 1C (`_legacy.py` → `reliability.py` не legacy, misleading) |

### Phase 2 (отдельная волна): rename + bulk-DEPRECATE

Phase 2A: rename `_legacy.py` → `reliability.py` (5 sibling imports,
straightforward refactor).

Phase 2B: bulk-DEPRECATE остальных shim где docstring явно говорит
deprecated + canonical API exists + telemetry показывает <5 external
importers.

## Inventory (cycle 152)

Полный список 15 backward-compat shim файлов с classification + external
importer count + recommendation:

| # | File | Class | Importer count | Action |
|---|---|---|---|---|
| 1 | `src/backend/services/io/external_database/__init__.py` | backward-compat | 1 | Phase 1B: audit + DEPRECATE |
| 2 | `src/backend/infrastructure/repositories/base/__init__.py` | sprint36-ponytail | 4 | keep (cycle resolution) |
| 3 | `src/backend/infrastructure/decorators/caching/__init__.py` | lazy-cache-instances | 2 | keep |
| 4 | `src/backend/infrastructure/database/database/__init__.py` | backward-compat | 16 | keep (active package) |
| 5 | `src/backend/infrastructure/clients/storage/s3_pool/__init__.py` | backward-compat | 6 | keep |
| 6 | `src/backend/infrastructure/clients/storage/redis/__init__.py` | backward-compat | 25 | keep |
| 7 | `src/backend/dsl/engine/processors/eip/reliability/_legacy.py` | misleading-name | 5 | Phase 2A: rename |
| 8 | `src/backend/dsl/builders/base/__init__.py` | stable-facade | 76 | keep (RouteBuilder canonical) |
| 9 | `src/backend/core/resilience/breaker.py` | stable-facade | 48 | keep (V16 canonical CB target) |
| 10 | `src/backend/core/config/services/mqtt.py` | backward-compat | 5 | keep |
| 11 | `src/backend/core/api/messaging.py` | ponytail-fix | 3 | keep (services→core.api) |
| 12 | `src/backend/core/facades.py` | **deprecation-candidate** | 1 | **Phase 1A: DEPRECATE ✓** |
| 13 | `src/backend/core/interfaces/__init__.py` | abc-contracts | 8 | keep |
| 14 | `src/backend/core/di/providers/infrastructure_facade.py` | already-deprecated | 1 | already has DeprecationWarning |
| 15 | `src/backend/entrypoints/grpc/grpc_server/__init__.py` | backward-compat | 5 | keep |

**Итого**: 13 keep + 1 deprecate-done + 1 rename-planned.

## Альтернативы (рассмотренные, отклонённые)

* **Массовое удаление шимов**: отклонено — сломает downstream tooling
  (76 импортёров `dsl.builders.base`, 48 `core.resilience.breaker`, 25
  `infrastructure.clients.storage.redis`). Контракт: testkit, core.api,
  RouteBuilder fluent-API нельзя ломать без ADR + telemetry.
* **Массовое добавление DeprecationWarning**: отклонено для active packages
  (16+ импортёров) — слишком много шума в logs прод. Deprecation
  только для shim с <5 импортёрами и explicit canonical replacement.
* **Regex-based rename `_legacy.py` → `reliability.py`**: отклонено —
  нужен ast-aware refactor с проверкой 5 sibling-imports на monkey-patch
  / string-paths. Безопасный rename — отдельный sub-wave.

## Последствия

**Плюсы**:

* `core/facades.py` помечен deprecated → telemetry покажет всех
  downstream-импортёров (target: 1 importer, можно планировать removal).
* 15 файлов классифицированы, ADR служит source-of-truth для будущих
  cleanup-волн.
* `infrastructure_facade.py` подтверждён как эталон (уже имеет warning).

**Минусы / риски**:

* DeprecationWarning в `core.facades.py` может зашумить в проде, если
  его импортируют в hot-path. Mitigated: telemetry cycle 153+
  покажет actual usage; removal target cycle 156.
* Rename `_legacy.py` требует аккуратного тестирования 5 sibling
  imports (через ast-aware refactor).

## Verification (cycle 152)

```
# 1. DeprecationWarning fires on import
python3.14 -W error::DeprecationWarning -c "import src.backend.core.facades"
→ DeprecationWarning: src.backend.core.facades is deprecated;
  use src.backend.core.api instead.

# 2. compileall clean
python3.14 -m compileall -q src/backend/core/facades.py → exit 0
python3.14 -m compileall -q src/ extensions/ scripts/ tools/ tests/  → exit 0

# 3. Import-graph integrity (no broken imports)
python3.14 -m pytest tests/unit -q -x --no-header 2>&1 | tail -10
→ 0 errors related to facades.py

# 4. ADR + INDEX registered
docs/adr/INDEX.md: ADR-0307 added (100 ADRs total).
```

## Связанные изменения (Phase 1A)

* **`src/backend/core/facades.py`** — добавлен `warnings.warn(DeprecationWarning,
  stacklevel=2)` на import модуля.
* **`docs/adr/0307-w3-p0-4-shim-inventory-classification.md`** — этот ADR.
* **`docs/adr/INDEX.md`** — ADR-0307 зарегистрирован (100 ADRs total).
* **`CHANGELOG.md`** — запись цикла 152 (W3 P0-4 Phase 1A).
* **`docs/roadmap/PROGRESS_LEDGER.md`** — wave-memo для cycle 152.

Refs: MINIMAX W3 (P0-4 shim inventory), ADR-0084, ADR-0249, Sprint 224
refactor (lazy proxies), cycle 152 (этот commit).