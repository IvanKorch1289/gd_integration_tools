# Minimax prompt v3 (corrected) — gd_integration_tools, 2026-09-23

> **Что изменено против v2** (факт-чек: `docs/audit/FACTCHECK_MINIMAX_V2_2026-09-23.md`):
> 1. **W0 «P0-блокер компилируемости» снят** — клейм «148 модулей не компилируются»
>    получен на Python < 3.14. На целевом рантайме (`requires-python=">=3.14,<3.15"`):
>    `compileall` → exit 0, guard-тест → 2 passed, `except A, B:` — валидный PEP 758
>    (ADR-0304, каноническая форма; ловит ОБА типа — проверено рантаймом).
> 2. W0 перепрофилирован в опциональную стилевую миграцию для Py<3.14-переносимости
>    (AST-инструмент готов: `tools/migrate_py2_except.py --check`).
> 3. Числа сверены с `docs/audit/MINIMAX_BASELINE.md` (измеренный recon; расхождения
>    с v2 отмечены). Порядок волн начинается с W1.
> 4. Блок функциональной верификации (cURL + Playwright) и все остальные волны
>    сохранены без изменений по смыслу.
>
> Статус исполнения на момент публикации: параллельная разработка уже прошла
> deadline-chain (ADR-0305), W2-prerequisite, W3 P0-4/P0-5, W4 P1-6 — перед
> стартом сверить каждую волну с `git log` и `PROGRESS_LEDGER.md`, не повторять.

---

## 0. ИЗМЕРЕННОЕ СОСТОЯНИЕ (факты — сверяй с `docs/audit/MINIMAX_BASELINE.md` на своём срезе)

- Масштаб: ~7k `.py`, `src/backend` ~350k LOC, тесты ~2138 файлов, Python **3.14 only**
  (`requires-python=">=3.14,<3.15"`). Любой статический анализ — только на 3.14.
- Качество: `ruff check src tests` — 0 (CI-гейт); цикломатика A (2.83).
- `compileall src/backend tools tests` (3.14) — **exit 0**; guard
  `tests/unit/test_py2_except_syntax_lint.py` — **2 passed**.
- `except A, B:` (PEP 758) — каноническая форма по ADR-0304, НЕ дефект.
  Опциональная скобочная миграция для Py<3.14-переносимости:
  `python3.14 tools/migrate_py2_except.py --root src --check` → `--write`.
- Гейты: `make lint` / `make type-check` — **warn-only** (не считай за proof);
  блокируют `lint-strict`, `type-check-budget`, `vulture-gate`, `layers`,
  `scan-isolated --strict`, `mypy_budget --max 5`.
- Дубли механик: circuit breaker ×2 (`core/resilience/circuit_breaker.py` 252 LOC,
  `entrypoints/middlewares/circuit_breaker.py` 435 LOC) + purgatory в deps;
  rate limiter — 3+ реализации.
- Две ветки процессоров: `dsl/processors/` (**28** файлов, legacy) vs
  `dsl/engine/processors/` (**318**, current) — числа по baseline-замеру.
- God-объекты: `dsl/builders/base/_protocols.py` (1094 LOC), RouteBuilder — 76 mixin
  в MRO, `core/di/providers/cache.py` (868 LOC), `manage.py` (1838 LOC).
- Совместимость: `__getattr__`-шимы ×64, compat/legacy/shim-модулей ×35,
  `raise NotImplementedError` в 45 файлах (по baseline).
- DI самописный (`core/di/module_registry.py` + importlib-обход layer-линтера).
- Недо-адаптированные библиотеки (ADR-0084): aiocache (пилот начат в W4),
  structlog (default=stdlib), typer/rich (0 использований).
- Отслеживаемые неблокирующие findings: `.claude/KNOWN_ISSUES.md` (re-verification
  2026-09-23) — object authorization (133 lookup'а без tenant-фильтра), privacy
  erasure (redis/s3/qdrant/ai_memory), alembic CONCURRENTLY vs SQLite, docstrings
  gate drift (250 missing / 46 файлов, claim «0» исторический).

## 1. ЦЕЛЬ (Definition of Done)

Проект: (1) чистая архитектура с явными границами; (2) читаемость для новых
разработчиков; (3) кастом → зрелые библиотеки с сокращением LOC; (4) без дублей
и мёртвого кода; (5) быстрый старт; (6) функциональные тесты через браузер и cURL.
Каждое изменение — атомарный коммит с зелёным **блокирующим** гейтом.

Инварианты: без placeholder/заглушек в прод-путях; fail-closed для security;
не выдумывать API/версии (проверять через `uv`); публичные контракты (testkit,
core.api, RouteBuilder fluent-API) не ломать без ADR; архитектурная развилка =
`make new-adr`. Правило достоверности: метрика доказана только командой на 3.14
с зафиксированным выводом — включая чужие отчёты (см. FACTCHECK-док).

## 2. ПОРЯДОК РАБОТЫ

1. Recon на своём HEAD: `python3.14 -m compileall -q src/backend` (exit 0),
   `make lint-strict`, `make type-check-budget`, `make vulture-gate`,
   `make layers`, `make deps-check-strict`, `make test`, `make scan-isolated`,
   `python tools/checks/generate_feature_inventory.py`. Сверить с
   `MINIMAX_BASELINE.md`; обновить числа на своём срезе.
2. Проверить `git log --oneline -30` + `docs/roadmap/PROGRESS_LEDGER.md` —
   часть волн уже выполнена параллельной разработкой; не повторять сделанное.
3. Волны строго по разделу 7; одна волна = один PR.
4. Код → unit → функциональный тест (cURL + браузер) → блокирующий гейт → коммит.
5. Отчёт: CHANGELOG + ADR (при развилке) + запись в PROGRESS_LEDGER.

## 3. ВОЛНЫ (после факт-чека)

- **W1 — консолидация резилиенса**: единый Circuit Breaker поверх purgatory
  (слить 2 реализации в один адаптер); единый Rate Limiter (3+ → 1 + тонкие
  адаптеры). ADR обязателен.
- **W2 — слияние веток процессоров**: `dsl/processors/*` (28) →
  `dsl/engine/processors/*` с re-export на 1 релиз, затем удалить.
- **W3 — шимы и stubs**: инвентаризация `__getattr__` ×64 + compat ×35;
  deprecate (PEP 702/warnings) → удалить при 0 внешних импортеров
  (`grep -rl` по src/tests/extensions/routes/tools + registry-scan);
  `.pyi`-drift RouteBuilder — автоген (`tools/gen_dsl_stubs.py`) или удалить.
- **W4 — aiocache** вместо ~681 LOC самописных async cache-декораторов
  (sync `lru_cache` оставить; существующие stampede-метрики
  coalesced/stale/lock_timeout сохранить).
- **W5 — structlog** как default-бэкенд логирования (переключить фабрику,
  мигрировать observability/*, сохранить GELF-путь).
- **W6 — typer+rich**: декомпозиция `manage.py` (1838 LOC) на под-команды.
- **W7 — DI**: оценить dishka; минимум — формализовать scopes и убрать
  importlib-обход layer-линтера. ADR с trade-offs.
- **W8 — RouteBuilder композиция** (Protocol-контракты готовы), малыми шагами.
- **W9 — god-objects + честные docs** (README/ARCHITECTURE ↔ факты).
- **W10 — P3**: старт-тайм (<3s, lazy AI/RAG deps), профилирование
  Exchange/Pipeline, orjson/msgspec на границах,
  Airflow-подобное (backfill/catchup — ОСТАЁТСЯ; sensor-процессоры —
  ГОТОВО: `SensorProcessor` poke/reschedule, ADR-0305-integrated,
  `eip/flow_control/sensor.py`), OTEL-propagation
  сквозь Saga/Temporal, DX-scaffold (`make new-route` с cURL+браузер скелетом).
- **EIP-полнота — ЗАКРЫТА (верифицировано 2026-09-23)**: каталог
  `dsl/engine/processors/eip/` уже содержит Aggregator (`flow_control/aggregator`,
  `aggregation.BatchAggregator`, collection-агрегаторы SumBy/MaxBy/MinBy/SortBy),
  Resequencer (`sequencing.py`), Splitter (`transformation.py`),
  Wire Tap (`flow_control/wire_tap.py`), Dead Letter + RedeliveryPolicy +
  FallbackChain + CircuitBreaker (`resilience.py`, `reliability/`),
  Idempotent Consumer, Claim Check, Content Enricher, Routing Slip,
  Transactional Client + Process Manager (Saga), Delay/Throttler/Loop/
  ForEach/OnCompletion, Multicast/ScatterGather/RecipientList/LoadBalancer/
  DynamicRouter. Клейм v2 «добавить Aggregator/Resequencer/WireTap/DLC» —
  не соответствует факту; перед добавлением новых EIP — сверять с каталогом.
- **W0 (опционально, стиль)**: скобочная форма `except (A, B):` для
  Py<3.14-переносимости — ТОЛЬКО как осознанное решение (118+ файлов, шум в
  blame); инструмент: `tools/migrate_py2_except.py`; guard-тест и compileall
  уже зелёные — делать нечего не требуется.

## 4. АРХИТЕКТУРНЫЙ ЧЕК-ЛИСТ (на каждый PR)

1. Направление зависимостей: entrypoints → services → core/dsl → infrastructure;
   обратные (core→infra/services) только уменьшать; `make layers` = 0 новых.
2. «Один способ сделать X» — никаких параллельных реализаций одной механики.
3. Ловить: god object, tight coupling, hidden state, weak typing, premature
   optimization, overengineering, mock-fallback вместо fail-closed.
4. Новая зависимость: зрелость, поддержка, порог входа, docs, ecosystem-fit,
   тестируемость, lock-in риск, доступность в РФ.

## 5. ФУНКЦИОНАЛЬНАЯ ВЕРИФИКАЦИЯ (cURL + браузер) — без неё волна не закрыта

### 5.1 Окружение

```bash
make dev-light   # APP_PROFILE=dev_light, без Docker; либо make dev / make run-all
```

### 5.2 cURL-smoke (все затронутые волной протоколы; фиксировать команда → ответ → ожидание)

```bash
curl -sf http://localhost:8000/api/v1/tech/check-all-services | jq .
curl -sf http://localhost:8000/api/v1/admin/system-info | jq .
curl -sf -X POST http://localhost:8000/api/v1/dsl/dispatch -H 'Content-Type: application/json' \
  -d '{"action":"orders.get","payload":{"order_id":1}}' | jq .
curl -sf -X POST http://localhost:8000/graphql -H 'Content-Type: application/json' \
  -d '{"query":"{ __typename }"}' | jq .
curl -sf "http://localhost:8000/api/v1/admin/feature-flags/toggle?flag_name=<flag>&enable=false"  # ожидаем 503 на защищённом
curl -sf http://localhost:8000/soap/wsdl | head -5
curl -sf http://localhost:8000/openapi.json | jq '.info.version'
# cross-tenant isolation (middleware order 330): без X-Tenant-ID на resource-URL с
# зарегистрированным checker'ом ожидаем 403 (fail-closed)
```

Критерий: 2xx (или ожидаемый 503/403/404 по контракту), `make api-fuzz` без регрессий.

### 5.3 Браузер (Playwright в стеке)

```bash
uv run playwright install chromium
uv run pytest tests/e2e -m e2e -q
```

Минимальный smoke: `/docs` — «Try it out» на затронутом эндпоинте → 2xx;
`/redoc` рендерится; Streamlit `:8501` — без console.error; скриншот-артефакт
в `artifacts/e2e/`.

### 5.4 Блокирующий гейт перед коммитом

```bash
python3.14 -m compileall -q src/backend   # exit 0
make format && make lint-strict && make type-check-budget && make vulture-gate && make test && make ci
make readiness-check
```

## 6. ФОРМАТ ОТЧЁТА ПО ВОЛНЕ

1. Вердикт (сделано/риск/статус блокирующего гейта).
2. Изменения (файлы; −LOC/+LOC).
3. Команды установки/запуска/тестов.
4. Верификация: вывод cURL + Playwright (скриншот).
5. Риски и откат (`git revert <sha>`).
6. Следующий шаг (одна волна вперёд).
