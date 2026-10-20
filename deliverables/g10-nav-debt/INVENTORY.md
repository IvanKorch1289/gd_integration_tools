# G10 navigation-debt — inventory & wave plan (pre-grilling)

> **Source of truth**: `docs/architecture/repository-navigation-audit.md` (118 строк, 8 секций, audit от 2026-09-11)
> + `docs/roadmap/PROD_READINESS_GAPS.md::G10`
> + live state репо на 2026-10-19 (commit `0801775639bc`).
> **Status**: pre-grilling inventory. Apply.py НЕ создан.
> **Goal**: предоставить полный fact-pack для решения пользователя о wave-планировании.

## Контекст

Audit (2026-09-11) обнаружил ~20 кандидатов на CONSOLIDATE / DEPRECATE / MOVE / DELETE_CANDIDATE.
Sprint 47 (commits `291dfeeab`/`9cf3429ba`/`8f62c06bb`) частично закрыл G8 и один пункт G10
(`core/services/base_external_api.py` дубль уже удалён). Остальное — открыто.

## Атомарная инвентаризация (20 кандидатов)

### Категория A: уже сделано (1 кандидат)

| ID | Кандидат | Audit verdict | Фактическое состояние | Действие |
|---|---|---|---|---|
| A1 | `core/services/base_external_api.py` (байт-в-байт дубль) | DELETE_CANDIDATE | Файл отсутствует (md5 только у `services/core/base_external_api.py`); удалён между 2026-09-11 и 2026-10-19 | Ничего — закрыто. Подтвердить через `git log` удаление. |

### Категория B: 0 prod consumers, можно удалять (4 кандидата)

| ID | Кандидат | Audit verdict | Verified (2026-10-19) | Действие |
|---|---|---|---|---|
| B1 | `src/backend/dsl/setup.py` | DELETE_CANDIDATE — `bootstrap_dsl` не вызывается в src/extensions (только тест) | Файл есть; grep `from .setup import\|import setup` (исключая mutants/): **0 prod импортов** | `git rm` + проверка что mutants/tests тоже больше не ссылаются |
| B2 | `src/backend/dsl/audit_versioning.py` (368 LOC) | DEPRECATE — 0 прод-импортов, жив только тестами | Файл есть; grep: **0 prod импортов** | `git rm` + проверить test-mutants зависимость |
| B3 | `src/backend/dsl/orchestration/__init__.py` (5349 B scaffold) | DEPRECATE scaffold (Sensor/Backfill/DryRun/HITL); `triggers.py` (20 KB) в том же пакете — живой (10 import-сайтов) | Файл есть; пакет `dsl/orchestration/` жив (`triggers.py`) | Удалить `__init__.py`, оставить `triggers.py`; **предлагаемый** rename каталога → `dsl/route_triggers/` (audit рекомендация для снятия коллизии имён с `workflow/orchestrator*`) |
| B4 | `src/backend/dsl/engine/processors/ai/banking_processors/base.py` | DELETE_CANDIDATE — остаток миграции в `ai_banking/`, 0 внешних импортов, нет `__init__` | grep `banking_processors.base`: **0 импортов** | `git rm` + проверить что migration в `ai_banking/` уже complete |

### Категория C: replaced by newer module (2 кандидата)

| ID | Кандидат | Audit verdict | Verified (2026-10-19) | Действие |
|---|---|---|---|---|
| C1 | `src/backend/entrypoints/email/` (`imap_monitor.py` + `__init__.py`) | DEPRECATE — заменён `infrastructure/sources/email.py` | grep `from .email\|import.*\.email`: **0 prod импортов** (только mutants + tests/unit/entrypoints/email/) | `git rm -r entrypoints/email/` + проверить что `infrastructure/sources/email.py` действительно production-ready (smoke test); удалить tests/unit/entrypoints/email/ |
| C2 | `src/backend/entrypoints/scheduler/` (`invoker_schedule.py` + `__init__.py`) | DEPRECATE — test-only | grep `from .scheduler`: **0 prod импортов** (только mutants + tests/unit/entrypoints/scheduler/) | `git rm -r entrypoints/scheduler/` + перенести test-only код если он ещё нужен (например, в `testkit/`) |

### Категория D: back-compat shim (2 кандидата)

| ID | Кандидат | Audit verdict | Verified (2026-10-19) | Действие |
|---|---|---|---|---|
| D1 | `src/backend/core/facades.py` (compat-shim `core.api import *`) | DEPRECATE — 0 прод-inbound, жив только self-тестом `tests/unit/core/test_facades_shim.py` | grep `from .facades\|import.*facades` (исключая test_, mutants/, __pycache__): **0 импортов** | Удаление в следующий release cycle (audit план: cycle 241). Требует dual-release window. |
| D2 | `src/backend/dsl/engine/processors/ai_processors.py` | DEPRECATE — back-compat shim (ADR-0102), удаление запланировано S84+ | Файл есть; ADR-0102 (нужна верификация — `find docs/adr -name "0102*"`). | Удаление в S84+ (audit план). Не сейчас. |

### Категория E: legacy migration in progress (3 кандидата)

| ID | Кандидат | Audit verdict | Verified (2026-10-19) | Действие |
|---|---|---|---|---|
| E1 | `src/backend/dsl/macros.py` | DEPRECATE — задокументированный shim; `templates_library.py:148,162` ещё на нём | Файл есть; нужна верификация конкретных вызовов | Перевести `templates_library.py` на `dsl.blueprints` (отдельная задача) |
| E2 | `src/backend/dsl/processors/{plan_execute,reflection_loop}_processor.py` (386 + 379 LOC) | CONSOLIDATE — независимые реализации с живыми потребителями по обе стороны | grep `builders/base/__init__.py:89\|builders/agent_dsl/orchestration.py:263` — нужна верификация | Миграция builders-колл-сайтов (отдельная волна) |
| E3 | `src/backend/dsl/builders/saga_lra.py` (398 LOC) | CONSOLIDATE — дубль с `dsl/engine/processors/saga_lra.py` | Файл есть; нужна верификация | То же — миграция builder-сайтов на engine/processors/saga_lra |

### Категория F: directory rename (2 кандидата)

| ID | Кандидат | Audit verdict | Verified (2026-10-19) | Действие |
|---|---|---|---|---|
| F1 | `src/backend/plugins/` → переименовать в `composition/` | MOVE (с re-export shim) | `src/backend/plugins/composition/` существует (composition-root: app_factory, di, setup_*) | `git mv src/backend/plugins src/backend/composition` + добавить `src/backend/plugins/__init__.py` с re-export для backward-compat (если есть импорты) |
| F2 | root `plugins/example_plugin/` (legacy yaml) → `extensions/example_plugin/` | CONSOLIDATE (там уже есть `plugin.toml`) | root `plugins/example_plugin/plugin.yaml` есть | Merge root `plugins/example_plugin/` в `extensions/example_plugin/` (если ещё не сделано) |

### Категория G: architectural move (3 кандидата)

| ID | Кандидат | Audit verdict | Verified (2026-10-19) | Действие |
|---|---|---|---|---|
| G1 | `src/backend/services/workflows/hitl_signal_store_redis.py` | MOVE → infrastructure | Нужна верификация (не делал) | `git mv` + import-rewrites в колл-сайтах |
| G2 | `src/backend/infrastructure/messaging/dlq/policy_resolver.py` | MOVE → core/messaging | Нужна верификация | `git mv` + import-rewrites |
| G3 | `src/backend/infrastructure/messaging/dlq/cleanup_job.py` (+lifecycle) | MOVE → services/ops | Нужна верификация | `git mv` + import-rewrites |

### Категория H: direct facade bypass (1 кандидат)

| ID | Кандидат | Audit verdict | Verified (2026-10-19) | Действие |
|---|---|---|---|---|
| H1 | `src/backend/services/ops/health.py:444` | CONSOLIDATE — прямой `redis.asyncio.Redis(...)` мимо фасада `get_redis_client` | Нужна верификация (не делал) | Заменить 1 строку на `get_redis_client()` |

### Категория I: protocol orphan (1 кандидат)

| ID | Кандидат | Audit verdict | Verified (2026-10-19) | Действие |
|---|---|---|---|---|
| I1 | mqtt entrypoint | CONSOLIDATE — 0 потребителей, в lifespan не стартует | grep `MqttHandler\|entrypoints.mqtt`: **2 prod потребителя** (`infrastructure/sinks/mqtt_sink.py`, `plugins/composition/di.py`) — **audit неточен** | Требует доппроверки: возможно, не CONSOLIDATE, а KEEP или DEPRECATE. Audit 2026-09-11 мог быть до добавления sinks. |

### Категория J: ASGI-incompatible (1 кандидат)

| ID | Кандидат | Audit verdict | Verified (2026-10-19) | Действие |
|---|---|---|---|---|
| J1 | `middlewares/admin_audit.py` + `observability.py` | DEPRECATE — orphan, BaseHTTPMiddleware несовместим с pure-ASGI | grep: tests есть, prod usage нужна верификация | Если prod usage = 0 → DELETE; иначе → конвертировать в pure ASGI или KEEP |

## Wave-план (предлагаемый)

### Wave 1: safe deletes (~1 PR, низкий риск)
- A1: подтвердить уже удалено
- B3: `__init__.py` remove + `triggers.py` оставить (0 references в mutants/tests)
- B1, B2, B4: 3 файла `git rm` — **НЕ БЕЗОПАСНЫ для Wave 1** (см. ниже)

**Verification (2026-10-19, post-INVENTORY fact-check):**
- A1: `core/services/base_external_api.py` подтверждённо отсутствует. ✅
- B1: 53 references в `mutants/tests/` (включая `test_setup.py`, `test_sqladmin_setup.py`, `test_otel_setup.py`). **Grep-pattern в INVENTORY был слишком узкий** (`from .setup import`); фактически имя файла `setup.py` встречается в 53 местах. Безопасное удаление требует миграции/удаления всех 53.
- B2: 12 references в `mutants/tests/` (включая 3 dedicated test-файла для `audit_versioning`). **Grep-pattern в INVENTORY был слишком узкий** (`from .audit_versioning import`); фактически реальный test-code ссылается. Удаление требует миграции тестов.
- B3: 0 references, scaffold-only файл. ✅ Безопасно удалять.
- B4: 108 references в `mutants/` (включая `.meta`, `.spans`, `.env` files — не real test code, но grep-фильтр нужен). **Grep-pattern в INVENTORY был слишком узкий**. Удаление требует careful pattern-based review.

**Скорректированный Wave 1 (только реально safe):**
- A1 (verify-only, no action needed)
- B3 (scaffold delete)

**Что переехало в Wave 1.5 (нужна тестовая миграция):**
- B1 (53 ref → migrate или delete mutants-тесты)
- B2 (12 ref → migrate 3 dedicated test-файла)
- B4 (108 ref → pattern-based review; многие `.meta/.spans` — mutant instrumentation, не real code)

**Estimated time:** Wave 1 (A1 + B3) = 5 минут. Wave 1.5 (B1+B2+B4) = 4-8 часов (тестовая миграция).

### Wave 2: replaced-by-newer (~1 PR, средний риск)
- C1, C2: 2 каталога, требует smoke `infrastructure/sources/email.py`

**Размер PR:** ~2-4 файла (удаление + smoke).
**Требует верификации:** что replacement модули production-ready.
**Estimated time:** 2-3 часа + smoke-тест.

### Wave 3: architectural moves (~2-3 PR, средний риск)
- D1, D2, E1-E3, F1, F2, G1-G3, H1, J1: ~12 кандидатов

**Размер PR:** по 1-3 файла на кандидата, ~15-20 PR если атомарно.
**Требует:** import-rewrites, обновление тестов, возможно dual-release windows для D1/D2.
**Estimated time:** несколько дней.

### Wave 4: protocol orphan / mqtt (~1 PR, требует обсуждения)
- I1: mqtt — audit неточен, нужно re-discuss

**Размер PR:** неопределён.
**Estimated time:** требует re-architecture обсуждения.

## Что НЕ верифицировано в этой инвентаризации

Точные prod-импорт-сайты для:
- B1, B2, B3, B4 (grep делал на broad patterns; нужен точный)
- C1, C2 (аналогично)
- E1, E2, E3 (для CONSOLIDATE нужны ВСЕ call-сайты обеих сторон)
- F1, F2 (нужны все импорты `src.backend.plugins.*` и `plugins.*`)
- G1, G2, G3 (нужны call-сайты в services/workflows, infrastructure/messaging, services/ops)
- H1 (нужно прочитать services/ops/health.py:444 контекст)
- I1, J1 (нужны prod call-сайты)

Это требует **отдельной верификационной сессии** (5-10 grep-вызовов на кандидата) перед каждым wave.

## Метод верификации (для следующих сессий)

```bash
# Pattern: для каждого кандидата выполнить
# 1. Static analysis: grep импортов
grep -rln "from src.backend.<module>\|from .<submodule>\|import <module>" --include="*.py" . \
  | grep -v ".venv/" | grep -v "__pycache__" | grep -v "mutants/"

# 2. Dynamic analysis: какой код вызывает модуль в runtime?
#    (нужен coverage report или trace)

# 3. ADR-линк: какой ADR защищает модуль?
grep -rln "ADR-.*<module>\|<module>.*ADR" docs/adr/

# 4. CHANGELOG: когда модуль последний раз менялся?
git log --oneline -5 -- <module_path>

# 5. docs/DECISIONS.md: какие решения про модуль?
grep -n "<module>" .claude/DECISIONS.md
```

## Связь с G8

G10 — это **отдельная задача** с собственным wave-планом. G8 (doc-accuracy) — orthogonal и может быть применён независимо. Рекомендую:

1. **Сначала apply G8** (7 фиксов по 11 файлам, exit 0 dry-run, ready).
2. **Затем Wave 1 G10** (после re-verification).
3. **Wave 2-3 G10** — следующие спринты.

## Скоуп deliverable

**Этот файл — ТОЛЬКО ИНВЕНТАРЬ.** Apply.py для G10 не создан. Создание apply.py — отдельная задача после grilling round'а с пользователем (вопросы: какие wave'ы, какой риск-аппетит, какие CR-партнёры).
