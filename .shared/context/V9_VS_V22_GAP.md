# V9 vs V22 — Gap Analysis (02.06.2026, обновлено после факт-чекинга)

> **Сверка** стратегического плана v9 FINAL (Production Judgment, 26 недель) с
> фактическим состоянием `gd_integration_tools` V22.6 FINAL + V22.10.2.
> Источник v9: `/tmp/V9_ANALYSIS_PRODUCTION_JUDGMENT.md` (архив).
> Source of truth: `PLAN.md` V22.6 FINAL.
> **Данные факт-чекинга:** 02.06.2026, инструменты `wc`/`find`/`grep`/`ruff`/`tomllib`.

## Резюме

Из **15 эпиков v9**:
- **7 полностью закрыты** в V22 (S31-S36 + V22.10.2)
- **4 частично сделаны / требуют продолжения** (P1, P2, P8, P15)
- **1 устарел / решен жёстче v9** (P3)
- **3 остаются V23+ backlog** (P4, P7, P9)

**v9 точность факт-чекингом:** ~75%. Цифры god-файлов и CB/RateLimit — точные; coverage и sprint status — устарели.

## Факт-чек цифр v9 (02.06.2026)

| Метрика | v9 утверждал | **Реальность** | Δ |
|---------|:------------:|:--------------:|:-:|
| Python файлов | 2 584 | src=1533, ext=72, tests=844 (всего 2 449 в src+ext+tests) | -135 |
| LOC | 238 459 | 237 838 (только src/) | -621 |
| God-файлов (>300 LOC) | 166 | **166** ✅ | 0 |
| Из них >1000 LOC | — | 8 | — |
| 500-1000 LOC | — | 38 | — |
| 300-500 LOC | — | 120 | — |
| Noqa-директив | 1 502 | **1 677** | +175 |
| Coverage | 51% | V22 target=83%, S36 closed 90%+ pre-prod-check | — |
| ruff errors | — | 394 (269 fixable, 27 unsafe-fixable) | — |
| Python | 3.14+ (v9 риск) | `>=3.13,<3.14` (жёстче v9!) | -1 minor |
| nemo-guardrails | proposed, 🔴 | **отсутствует** в deps ✅ | — |

**v9 был точен в:** god-файлы 166 (точно), P1 кандидаты (5/5 в топе), P2.3 CB (3+ реализации), P2.4 RateLimit (3+ реализации).
**v9 устарел в:** coverage (51% → 83%+), S36 status (active → CLOSED), Python 3.14 риск (риск закрыт жёстче).

## Детальная сверка по эпикам v9

### ✅ Закрыты в V22 (S31-S36 + V22.10.2)

| v9 Epic | Что сделано (факт) | Артефакт |
|---------|---------------------|----------|
| **P0: Тесты 51%→83%** | V22.6 target=83%, S36 closed 90%+ pre-prod-check (38/38 gates) | `coverage_percent_min: 83` в PLAN.md |
| **P6: CDC завершение** | V22.10.2 wave 5: `cdc_client_adapter.py` — адаптер production `CDCClient` → `CDCSource` Protocol | +2 tests |
| **P10: Отказоустойчивость** | V22.10.2 wave 1: task_watchdog, backpressure, cache_decorators, retry, decorators — 5 critical fixes | 100 → 105+ tests |
| **P11: Performance** | V22 perf gates: p95 ≤80ms, RPS ≥1500, perf_gate_strict_p95_80ms feature-flag | S20 backbone |
| **P12: AI Guardrails** | S27 closure: 9 AI processors (agent_run/branch/loop/parallel, guardrails_apply, pii_mask/unmask, skill_invoke, memory_recall/store), AI_GATEWAY_ENFORCE=true | S27.closure (PLAN.md) |
| **P13: RPA + DSL** | V22.10.2 wave 6: `PdfReadProcessor` → `utilities/pdf_reader.read_pdf`, `ArchiveProcessor` content fallback | +2 tests |
| **P14: Документация** | S34 w1-w5: Sphinx, Diátaxis, docstring gate, Vale; S36: Sphinx docs ≥95% | `make docs-coverage` |

### 🟡 Частично / требует продолжения

| v9 Epic | Сделано | Осталось | Приоритет V23 |
|---------|---------|----------|:-------------:|
| **P1: God-объекты** | V22.10.2 wave 7: vulture/deptry baseline, ARCHITECTURE.md | **5/5 кандидатов v9 в топе**: features.py 2825, integration.py 2183, providers.py 1234, lifecycle.py 1100, gateway.py 1091. Декомпозиция. | 🟠 **P1.1** |
| **P2.1-2 Cache + Logging** | ✅ V22.10.2 wave 3 (cache) + wave 2 (logging) | — | ✅ done |
| **P2.3 CB 3→1** | — | **5+ реализаций**: `infrastructure/resilience/client_breaker.py`, `infrastructure/clients/external/circuit_breakers.py`, `infrastructure/clients/transport/{http,http_httpx,smtp}.py` (embedded), `dsl/engine/processors/eip/resilience.py`, `core/resilience/{resilience_profile,decorators}.py`. Выбор канонического. | 🟠 **P2.3** |
| **P2.4 RateLimit 3→1** | — | **4+ реализации**: `infrastructure/resilience/{unified_rate_limiter,distributed_rl_cluster,rate_limiter}.py`, `services/execution/middlewares/rate_limit_middleware.py`, `core/resilience/{rate_limiter,_pyrate_compat}.py`. | 🟡 **P2.4** |
| **P8: ConvertersMixin 35** | S19 deprecation начат | Целевая метрика 150→70-90 cohesive methods к V23 (removal) | 🟡 V23 |
| **P15: Cleanup + Security** | V22.10.2 wave 7: vulture/deptry baseline; S35: SBOM+cosign, OWASP ZAP, pip-audit | **1677 noqa** (v9 говорил 1502 — занижено). Plan ratchet: 1677→<500 к V23. | 🟡 **P15.1** |

### ⚠️ Устарел / решён жёстче v9

| v9 Epic | v9 рекомендация | **Реальность** | Статус |
|---------|-----------------|----------------|:------:|
| **P3: Python 3.14 pydantic-core** | v9 рекомендовал `>=3.13,<3.15` (Вариант А) | **`requires-python = '>=3.13,<3.14'`** — **жёстче v9**, исключает 3.14 полностью. `AGENTS.md` говорит "Python 3.14+" — **устарело/баг**, требует фикса. | ⚠️ **FIX: AGENTS.md** |
| **P5: Docker Compose infra** | v9 предлагал docker-compose.infra.yml | V22 использует K8s Helm chart (S20 backbone). Compose — не приоритет. | 🟢 не нужно |

### ❌ Остаются V23+ backlog

| v9 Epic | Оценка v9 | Зависимости |
|---------|-----------|-------------|
| **P4: Consul** для констант | 2-3 нед | Требует инфраструктурного решения (Consul в org). V23 бэклог. |
| **P7: Groovy DSL P1** (Collect, FindAll, GroupBy, OrElse) | 2-3 нед | Можно независимо. 4 процессора в `dsl/engine/processors/`. |
| **P9: Groovy DSL P2+P3** (Find, Sort, Each, Flatten, Unique, Plus, EachWithIndex, Intersect, Minus) | 2-3 нед | Зависит от P7 (тот же engine/processors/). |

## Расхождения v9 ↔ V22 (факт-чек)

| v9 утверждение | Реальность | Коррекция |
|----------------|------------|-----------|
| "Sprint 36 — Production Readiness 90%+" (active) | **CLOSED** 2026-08-31 (38/38 gates) | v9 писался до closure |
| "Тестовое покрытие 51%" | V22 target = 83%; baseline 50% (S34) → ratchet 75% (S19) → 83% (S20) | Устарело, обновлено в V22 |
| "pydantic-core 🔴 блокирует 3.14" | `requires-python = '>=3.13,<3.14'` — исключает 3.14 полностью | Решено жёстче v9 |
| "166 god-файлов" | **166 ✅** | Точно |
| "1 502 noqa" | **1 677** | v9 занизил на 175 |
| "9 анализов (65+ агентов)" | Не воспроизводимо | Считать black-box |
| "V23 backlog, 26 недель" | Подтверждается: `post-v22-backlog/` уже создано | Корректно |

## Список задач V23 (приоритезировано, без выдумок)

### 🔴 P1.1 — God-файл `features.py` (2825 LOC)

**Файл:** `src/backend/core/config/features.py`
**Проблема:** Один файл содержит feature-flags для всего проекта (v9 явно указывал).
**Подход:**
- Аудит содержимого (какие флаги, какие категории)
- Группировка по доменам: auth, resilience, ai, infra, experimental
- Создание `core/config/features/{auth,resilience,ai,infra,experimental}.py` + re-exports
- Сохранение backwards-compat через `features.__getattr__`
- **Риски:** очень многие импорты; циклические зависимости при перемещении
- **Объём:** 5-7 дней (аудит + декомпозиция + тесты)
- **Coverage gate:** 0 регрессий (этот файл — критический)

### 🟠 P2.3 — Circuit Breaker консолидация (5+ → 1)

**Файлы-кандидаты на консолидацию:**
1. `infrastructure/resilience/client_breaker.py` — low-level CB
2. `infrastructure/clients/external/circuit_breakers.py` — per-client CB
3. `dsl/engine/processors/eip/resilience.py` — DSL EIP wrapper (использует п.1)
4. `core/resilience/{resilience_profile,decorators}.py` — profile-based API
5. `infrastructure/clients/transport/{http,http_httpx,smtp}.py` — embedded inline

**Подход:**
- Аудит: какой API реально используется (callsite count)
- Выбор канонического: `core/resilience/decorators.py` (v22.10.2 wave 1 зафиксировал API)
- Deprecation остальных: `DeprecationWarning` + `post-v22-backlog/`
- **Объём:** 3-5 дней

### 🟡 P2.4 — Rate Limit консолидация (4+ → 1)

**Файлы:**
1. `infrastructure/resilience/unified_rate_limiter.py` ← v9 кандидат
2. `infrastructure/resilience/distributed_rl_cluster.py`
3. `infrastructure/resilience/rate_limiter.py` (legacy)
4. `services/execution/middlewares/rate_limit_middleware.py`
5. `core/resilience/rate_limiter.py`
6. `core/resilience/_pyrate_compat.py` (compat shim)

**Подход:**
- Аудит + выбор канонического (вероятно `unified_rate_limiter.py`)
- Deprecation + re-exports
- **Объём:** 3-5 дней

### ⚠️ FIX — AGENTS.md Python version

**Файл:** `AGENTS.md` строка с "Python 3.14+"
**Реальность:** `pyproject.toml::requires-python = '>=3.13,<3.14'`
**Действие:** Один-line fix, согласование с правилом Python 3.13 (исключая 3.14)
**Объём:** 5 мин + 1 PR

### 🟡 P7 — Groovy DSL P1 (4 процессора)

**Файлы:** `src/backend/dsl/engine/processors/`
**Новые процессоры:**
- `CollectProcessor` — `.collect(field="name")`
- `FindAllProcessor` — `.find_all(condition="age > 18")`
- `GroupByProcessor` — `.group_by(field="category")`
- `OrElseProcessor` — `.or_else(default="N/A")`
**Объём:** 2-3 нед (каждый процессор + тесты + docs)

### 🟢 Не делать в V23 (отложено)

- **P4 Consul** — нужна инфра-решение
- **P9 Groovy DSL P2+P3** — после P7
- **P5 Docker Compose** — K8s Helm достаточно
- **P8 ConvertersMixin cleanup** — S19 deprecation, removal в V24+

## Owner / когда

Все эпики V23 — **post-S37 planning**. Текущий Sprint 37 W1 — multi-agent infra (фазы 2-5 done), фаза 6 (smoke-тест Claude+Kimi) — следующая.

## Куда положить артефакты

- `post-v22-backlog/` — V23+ removal ledger (S19 ADR-NEW-10)
- `.shared/context/V9_VS_V22_GAP.md` — этот файл
- `TECH_DEBT.md` — append-only ledger для найденных проблем
