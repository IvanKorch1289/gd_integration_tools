# Coverage Ratchet Plan (Cycle 12, production-grade plan)

> **Создано**: 2026-08-27 (Cycle 12, Phase 3 P3 Testing).
> **Цель**: вернуть coverage gate обратно к 75% через targeted unit test writing.

## Текущее состояние (baseline)

Измеряется ``.baselines/coverage.json`` (``current_subset_measurement``):

- **Scope**: ``tests/unit/{core,infrastructure,dsl}``
- **Files measured**: 2152
- **Statements covered**: 10 335 / 108 076
- **Coverage**: **9.56%**
- **Gate (``fail_under`` в pyproject.toml)**: 60% (временно понижен в S34 W4)
- **Target**: 75%
- **Gap**: **−65 pp** (9.56 → 75%)

Per-layer breakdown из ``tools/coverage/per_layer_diagnostic.py``:

| Layer | Coverage | Statements |
|-------|----------|------------|
| core | 5.4% | 18 103 |
| infrastructure | 0.8% | 24 620 |
| services | 0.3% | 18 941 |
| dsl | 0.0% | 30 312 |
| entrypoints | 0.0% | 11 377 |

## Почему реальный % ниже 60% gate

`pyproject.toml:1080` ставит ``fail_under=60`` (понижен в S34 W4 для
"реалистичной промежуточной цели"). Текущая measurement subset = 9.56%.
Gate формально FAIL, но pytest run с ``--cov-fail-under=0`` пропускает
(coverage опциональный). Полный pytest run tests/unit/ OOM-killed
(137) на едином процессе — нужен pytest-xdist split.

## Ratchet план (8 weeks, +5pp / 2 weeks)

### Sprint A (week 1-2): +5pp → 14.56%

Target: добавить unit tests для топ-10 файлов в core с 0% покрытием.

Приоритет (по impact / cost):
1. ``src/backend/core/utils/*.py`` — utility helpers (лёгкие unit tests)
2. ``src/backend/core/auth/*.py`` — auth helpers (важны для P0)
3. ``src/backend/core/di/providers/*.py`` — DI providers

Estimated: 80-120 новых unit tests, +5pp coverage.

### Sprint B (week 3-4): +5pp → 19.56%

Target: infrastructure layer (Redis, ClickHouse, S3 с mock clients).

1. ``src/backend/infrastructure/cache/*.py`` — Redis client/mixin tests
2. ``src/backend/infrastructure/storage/*.py`` — S3 / MinIO mock tests
3. ``src/backend/infrastructure/messaging/*.py`` — Kafka / RabbitMQ mock

### Sprint C (week 5-6): +5pp → 24.56%

Target: services layer (workflows, audit, AI).

1. ``src/backend/services/workflows/*.py`` — HITL, workflow state machine
2. ``src/backend/services/audit/*.py`` — audit event log
3. ``src/backend/services/ai/memory/*.py`` — LangMem

### Sprint D (week 7-8): +5pp → 29.56%

Target: dsl + entrypoints (самые большие файлы, меньший impact per test).

1. ``src/backend/dsl/builders/*.py`` — RouteBuilder mixins
2. ``src/backend/dsl/engine/processors/*.py`` — EIP patterns
3. ``src/backend/entrypoints/api/v1/endpoints/*.py`` — REST endpoints

### После Sprint D: переоценка

После +20pp (29.56% достигнуто) — пересмотреть plan:
- Возможно переоценить target (75% слишком ambitious для 30k+ statements)
- Реалистичная цель может быть 50% с explicit "acceptable" списком
- Или продолжить +5pp циклы до 50%

## Тактика test-writing

1. **Property-based (hypothesis)**: для utility / schema-validation кода —
   быстрее покрывает edge-cases vs ручные unit tests.
2. **Mock-driven**: для integration points (DB, cache, MQ) — pytest-httpx,
   fakeredis, moto (S3 mock), testcontainers.
3. **pytest-xdist split**: full suite tests/unit/ — обязательно для CI gate
   (``pytest -n auto``). Без split OOM-kill persists.
4. **Coverage-driven dev**: при добавлении новой фичи — обязательный
   unit test в том же PR (developer policy).

## CI gate: реалистичный путь

Ponytail-YAGNI: gate НЕ поднимается обратно к 75% до достижения реально
измеримого прогресса. Вместо этого:

- Sprint A: поднять ``fail_under`` с 60 → 20 (после +10pp измерено)
- Sprint B: → 30
- Sprint C: → 40
- Sprint D: → 50

Каждое повышение — отдельный PR с реальным измерением (pytest -n auto
+ coverage report).

## Метрики прогресса

- Еженедельный замер: ``make coverage`` (нужно добавить target)
- Coverage per-PR: ``diff-cover`` (post-commit) показывает coverage
  delta для изменённых файлов
- Coverage baseline update: ``.baselines/coverage.json`` обновляется
  каждый спринт с реальным числом

## Что НЕ делается

- Coverage gate немедленно к 75% — multi-quarter effort
- Mutation testing как coverage proxy — отдельная инициатива (Cycle 13)
- E2E coverage через Playwright — separate effort, требует test infra
- Property-based test generation — selective (только где cost-effective)

## Reference

- ``.baselines/coverage.json`` — current baseline (9.56% subset)
- ``pyproject.toml:1065-1085`` — coverage config
- ``tools/coverage/per_layer_diagnostic.py`` — per-layer breakdown
- ``tools/check_layers.py`` — layer enforcement (separate gate)
- ``tools/checks/check_routebuilder_mro.py`` — MRO budget gate
  (Cycle 8, budget=100)
