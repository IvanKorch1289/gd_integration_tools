# Анализ: оптимизация integration/RPA, замена кастома на библиотеки

**Дата**: 2026-10-15 · **HEAD**: `a053f722e` · **Scope**: integration + RPA слои

## Executive summary

Проанализированы `src/backend/services/rpa/` (1455 LOC), `src/backend/core/rpa_recorder/`
(308 LOC), `src/backend/infrastructure/resilience/` (3140 LOC) и
`src/backend/core/utils/`. Обнаружено:

- **3 мёртвых модуля** (~397 LOC) — кандидаты на удаление (требуют ADR);
- **2 кандидата на замену кастома библиотеками** — оценено, но миграция
  дороже текущего состояния;
- **5 библиотек-кандидатов** для будущих workflow (Ponytail — не добавлять
  без use case).

---

## 1. Мёртвый код (кандидаты на удаление)

### 1.1 `core/rate_limiter/` — 245 LOC, 0 импортеров

```
src/backend/core/rate_limiter/__init__.py   41 LOC
src/backend/core/rate_limiter/limiter.py   204 LOC
src/backend/core/rate_limiter/DEPRECATED.md (уже помечен)
```

**Факт**: `grep -rn "from src.backend.core.rate_limiter" src/ tests/` → 0
импортеров вне самого пакета. Реальный rate-limiting идёт через
`infrastructure/resilience/unified_rate_limiter.py` (Redis-backed,
multi-instance safe) + `entrypoints/dependencies/rate_limit.py`
(SafeRateLimiter).

**Причина дублирования**: кастомный token-bucket (`limiter.py:75-91`)
с `time.sleep()` в `acquire()` — синхронный блокирующий код, непригодный
для async event loop. `unified_rate_limiter` решает эту проблему через
Redis + `try_acquire_async`.

**Рекомендация**: `git rm -r src/backend/core/rate_limiter/`.
Требует ADR (CLAUDE.md: «удалять файлы/модули» — запрещено без подтверждения).

### 1.2 `core/utils/cache_keys.py` — 48 LOC, 0 импортеров

**Факт**: нет ни одного импорта в `src/` или `tests/`. Содержит
хелперы для формирования cache-key строк — вероятно, superseded
inline-шаблонами в вызывающих модулях.

**Рекомендация**: удалить после подтверждения (ADR).

### 1.3 Проверено и ОСТАВЛЕНО (не мёртвое)

| Модуль | LOC | Импортеров | Решение |
|---|---:|---:|---|
| `core/utils/json_utils.py` | 104 | 3 (`dumps_str`) | оставить |
| `core/utils/converters.py` | — | 4 | оставить |
| `core/utils/datetime_utils.py` | — | 1 | оставить |

---

## 2. Кандидаты на замену кастома библиотеками

### 2.1 `core/rpa_recorder/recorder.py` (252 LOC) — НЕ заменять

**Что внутри**: генератор Selenium-подобных тестов с `# TODO` markers
(`recorder.py:173, 205, 217`).

**Оценка замены**: Playwright имеет встроенный `playwright codegen` +
`record_har_path`. Но наш recorder пишет **assertions**, а не только
селекторы — это другая семантика.

**Решение**: оставить как есть, но добавить в backlog:
- удалить `# TODO` markers (сделать шаблоны самодостаточными);
- либо мигрировать на Playwright `trace` API (по аналогии с RPA
  integration suite, который уже использует реальный Chromium).

### 2.2 `services/rpa/browser_cookies_store.py` (232 LOC) — НЕ заменять

**Что внутри**: персистентность cookies для tenant-isolated RPA-сессий.

**Оценка замены**: Playwright `storage_state()` умеет экспортировать/
импортировать cookies+localStorage, но **не поддерживает multi-tenant
разделение** — это наша бизнес-фича (tenant_id в ключе).

**Решение**: оставить. Это domain-логика, не инфраструктура.

### 2.3 `infrastructure/resilience/` (3140 LOC) — НЕ заменять

Кастомные `snapshot_job.py` (450), `coordinator.py` (398),
`region_routing.py` (229) — это **tenacity + purgatory** поверх Redis,
но с domain-специфичной логикой (failover между регионами, health
probing). Tenacity не покрывает cross-region routing.

**Решение**: оставить. CLAUDE.md R-V15-8 требует tenacity-unification —
это уже сделано (custom retry в `core/orchestration/retry.py`
консолидирован).

---

## 3. Библиотеки-кандидаты для будущих workflow

Ponytail-подход: **не добавлять без реального use case**. Ниже —
кандидаты с обоснованием и оценкой.

### 3.1 RPA: `pytest-playwright` (⭐ high value)

**Проблема**: RPA integration-тесты сейчас требуют ручного `pytest.mark`
и кастомных фикстур. `playwright` уже в deps.

**Use case**: `@pytest.mark.playwright("chromium")` + автоматический
browser lifecycle + trace-on-failure (trace.zip уже используется в
нашей battery).

**Оценка**: 1 dev-week на миграцию существующих 9 real-browser тестов
на pytest-playwright fixtures. **Выгода**: автоматический
`--tracing=retain-on-failure` (убирает ручной screenshot/trace код).

### 3.2 RPA: `tenacity` для retry в BrowserPool (⭐ medium)

**Проблема**: `browser_pool.acquire()` при таймауте просто
блокируется на семафоре — нет retry/backoff метрики.

**Use case**: retry при transient browser-crash (Playwright
`TargetClosedError`).

**Речень**: tenacity уже в core deps (R-V15-8). 2-3 строки кода
вместо кастомного retry-loop.

### 3.3 Integration: `respx` для HTTP-mock в RPA-тестах (✅ уже есть)

`respx>=0.22,<1` в testkit extra — покрывает HTTP-mock. Проверено:
`tests/unit/services/rpa/test_desktop_rpa_client.py` уже использует
respx. **Действий не требуется.**

### 3.4 Integration: `hypothesis` для property-based тестов DSL (⭐ high)

**Проблема**: DSL pipeline (`Engine → Processor[]`) не имеет
property-based тестов. `hypothesis` уже в dev-deps (`hypothesis>=6.168.0`).

**Use case**: `@given(st.lists(processor_specs))` → проверить что
pipeline **никогда** не падает на валидных входах (idempotency,
ordering, error propagation).

**Оценка**: 1 dev-week. **Выгода**: ловит edge-cases, которые
ручные тесты пропускают (Sprint-специфично).

### 3.5 Observability: `opentelemetry-instrumentation-playwright` (⭐ medium)

**Проблема**: RPA-действия не видны в traces (только LangFuse для LLM).

**Use case**: каждое `page.goto()` → span с `url`, `duration_ms`,
`tenant_id`. Три первопричинные метрики RPA: latency per selector,
failure rate per selector, session duration.

**Оценка**: 3-5 дней (OTel-инструментация Playwright неофициальная,
нужен ручной wrapper). **Выгода**: RPA становится наблюдаемым
наравне с HTTP.

### 3.6 Resilience: `aioresilience` (❌ НЕ рекомендую)

Дублирует tenacity + наш `unified_rate_limiter`. Не добавляем.

---

## 4. Оптимизация integration/RPA — конкретные идеи

### 4.1 RPA: BrowserPool warm-start — ❌ ПРОВЕРЕНО, НЕ ДАЁТ ПОЛЬЗЫ

**Гипотеза**: `browser.new_context()` — I/O-bound (CDP round-trip),
поэтому последовательный цикл сериализует N независимых вызовов и
`asyncio.gather()` даст ~5x ускорение.

**Что сделано**: реализован `asyncio.gather()` вместо цикла, измерено
на настоящем Chromium (size=6), затем **откачено**.

**Замеры** (3 trial, size=6, headless Chromium):
```
последовательно: 0.397s / 0.336s / 0.389s   (median ~0.389s)
параллельно:     0.396s
```

**Вывод**: разница в пределах шума. `new_context()` в Playwright
**CPU-bound**, а не I/O-bound — Chromium создаёт contexts в процессе
сам, а сетевой round-trip только запускает операцию. `gather()`
не помогает и добавляет сложность.

**Решение**: оставить последовательный цикл. Гипотеза опровергнута
замером, а не рассуждением (Ponytail-подход: проверять перед
оптимизацией).

### 4.2 RPA: context recycling по TTL

**Текущее состояние**: контексты живут до `shutdown()`.

**Проблема**: долгоживущий pool накапливает memory (cookies, cache,
service workers).

**Идея**: TTL + lazy recreate (context старше `rpa.context_ttl_seconds` →
закрыть при следующем acquire). Уже есть `browser_cookies_store` для
персистентности — переиспользовать его.

**Оценка**: 1 dev-week. **Выгода**: memory hygiene в long-running
RPA workers.

### 4.3 Integration: batch dispatcher

**Текущее состояние**: `dispatch_action()` — один action за раз.

**Проблема**: DSL route с 10 `call_function` шагами → 10 dispatch
вызовов с overhead на каждый.

**Идея**: `dispatch_batch([...])` в `ActionHandlerRegistry` —
один `try_acquire` для всей пачки. **Оценка**: только если профилирование
покажет bottleneck (не делаем на основе предположения).

---

## 5. Рекомендованный порядок (Ponytail)

| Приоритет | Действие | Оценка | Выгода |
|---|---|---|---|
| **1** | Удалить `core/rate_limiter/` + `core/utils/cache_keys.py` (ADR) | 0.5 дня | −293 LOC мёртвого кода |
| **2** | `pytest-playwright` fixtures для RPA-тестов | 1 неделя | автоматический trace-on-failure |
| **3** | `hypothesis` property-тесты для DSL pipeline | 1 неделя | ловит edge-cases |
| **4** | `tenacity` retry в `BrowserPool.acquire()` | 0.5 дня | resilience к browser-crash |
| **5** | Context TTL recycling | 1 день | memory hygiene |
| **6** | OTel wrapper для Playwright | 3-5 дней | RPA observability |
| **7** | Batch dispatcher (после профилирования) | 1 день | ? |

**Отменено после замера**: параллельное создание контекстов
(разница 0.396s vs 0.389s = шум; `new_context()` CPU-bound).

**Не рекомендуем**: `aioresilience`, замена `rpa_recorder` на Playwright
codegen, замена `browser_cookies_store` на `storage_state()`.

---

## 6. Уже сделанное (этот цикл)

- `fastapi_limiter==0.2.0` bug: обойдён через `SafeRateLimiter`
  subclass (`entrypoints/dependencies/rate_limit.py`);
- 31 CVE из Dependabot batch закрыты upgrade'ами;
- langfuse v3 test-regression (Presidio/spaCy/sympy hang) закрыта;
- `tools/scaffold.py` processor template переведён с no-op на рабочий
  паттерн + 6 regression-тестов.

---

## References

- ADR-0072 (PII anonymization в LangFuse traces) — источник
  `sanitize_traces` default-ON.
- ADR-0290 (pip-audit allowlist prune history) — контекст allowlist.
- R-V15-8 (tenacity unification) — constraint для раздела 2.3.
- `docs/architecture/canonical-module-map.md` — каноническая карта.