# S38 — V23 Refactoring & Stabilization Plan

> **Sprint:** S38 (post-S37 W1)
> **Период:** TBD (после S37 W1 closure)
> **Owner:** Ivan (orchestrator) + К2 (resilience) + К3 (DSL)
> **Источник:** `.shared/context/V9_VS_V22_GAP.md` (v9 plan vs V22.10.2 факт-чек)
> **Reference v9:** `/tmp/V9_ANALYSIS_PRODUCTION_JUDGMENT.md`

## Цели спринта

1. Закрыть **P1.1** v9 — декомпозиция god-файла `features.py` (2804 LOC, главный кандидат v9)
2. Закрыть **P2.3** v9 — CircuitBreaker консолидация (5+ реализаций → 1 канонический)
3. Закрыть **P2.4** v9 — RateLimit консолидация (4+ реализаций → 1 канонический)

**Out of scope S38:**
- ❌ **P4 Consul** — в работе параллельным процессом (см. untracked `src/backend/core/config/consul_config.py`)
- ❌ **P7 Groovy DSL P1** — в работе параллельным процессом (см. untracked `src/backend/dsl/builders/collection.py`, `dsl/engine/processors/eip/collection.py`)
- ❌ P9 Groovy DSL P2+P3 — после P7
- ❌ P8 ConvertersMixin cleanup — S19 deprecation, V24+ removal

## Правила работы (S38-specific)

- **Ревью через `requesting-code-review` перед каждым коммитом** (обязательно, по решению Ivan).
- **Стоп после каждой Task** — показываю diff пользователю, жду «ок» перед следующей.
- **Атомарные коммиты**, префикс `[verified]` (см. requesting-code-review Step 8).
- **Не трогать uncommitted M-файлы** в working tree (чужие изменения от других процессов).
- **Git add конкретных файлов**, НЕ `git add -A` (чтобы не зацепить чужие изменения).
- **Graphify pre-commit hook: `--no-verify`** (известно: ~60s delay).
- **Python:** использовать `.venv/bin/python` (не `uv run` — orjson/purgatory отсутствуют).
- **Без `emoji`** в коммитах и сообщениях.
- **Без выдуманных улучшений** — итог = список сделанных задач.

## Definition of Done (S38)

- [ ] `features.py` декомпозирован на ≥3 модуля по доменам, backwards-compat сохранён
- [ ] CircuitBreaker: 1 канонический API, остальные — `DeprecationWarning` + re-exports
- [ ] RateLimit: 1 канонический API, остальные — `DeprecationWarning` + re-exports
- [ ] Groovy DSL: 4 процессора (Collect, FindAll, GroupBy, OrElse) с тестами ≥85% coverage
- [ ] `make lint && make type-check && make test` — все зелёные, 0 регрессий
- [ ] `make pre-prod-check` baseline сохраняется (38/38)
- [ ] `git log` S38: атомарные коммиты с `[verified]` prefix

## План по волнам

### W0 (1-2 дня) — Foundation

| ID | Задача | Трудоёмкость | Зависимости | DoD |
|----|--------|:------------:|-------------|-----|
| **T0.1** | ~~FIX: `AGENTS.md` "Python 3.14+" → "Python 3.13+" — 5 мин~~ | **ОТМЕНЕНО** | — | См. `.shared/context/TECH_DEBT.md` запись `python-version-doc-drift` |
| **T0.2** | Создать `post-v22-backlog/` ✅ | 0 | — | директория существует |
| **T0.3** | Baseline: `.baselines/noqa.json` = 1677 ✅ | 0 | — | файл валидный JSON |
| **T0.4** | Baseline: `make pre-prod-check` (зафиксировать 38/38 baseline) | 30 мин | — | JSON-отчёт с 38/38 + 0 регрессий |

**Стоп после W0.** Показать результат → согласование W1.

**T0.1 отменён:** реальный масштаб — 20+ файлов (документация, rules, UI, vault),
а не 1 строка в AGENTS.md. Решение требует от Ivan выбор Python target
(`>=3.13,<3.14` сейчас vs `>=3.14,<3.15` v9 Вариант А vs расширение окна).
Зафиксировано в TECH_DEBT.md как `python-version-doc-drift` (low severity).
Решение отложено в S39.

### W1 (3-5 дней) — P1.1 `features.py` декомпозиция

| ID | Задача | Трудоёмкость | Зависимости | DoD |
|----|--------|:------------:|-------------|-----|
| **T1.1** | Аудит: посчитать flags по доменам (K1, K2, K3, K4, K5, experimental) | 0.5 дня | T0.4 | таблица `flag_count` per domain в `.shared/context/P1_1_audit.md` |
| **T1.2** | Решить: какие домены → отдельные модули, какие → оставить в `features.py` | 0.5 дня | T1.1 | план split'а в `.hermes/plans/S38_W1_P1_split.md` |
| **T1.3** | Создать `core/config/features/{auth,resilience,ai,infra,experimental}.py` (skeleton, пустые классы) | 1 день | T1.2 | 5 новых файлов скелет |
| **T1.4** | Миграция: переместить flags из `features.py` в доменные модули (по 1 домену за раз) | 1-2 дня | T1.3 | коммит per domain + тесты |
| **T1.5** | Backwards-compat: `features.py` остаётся как re-export модуль (`__getattr__` или явный import) | 0.5 дня | T1.4 | `from features import feature_flags` работает |
| **T1.6** | Coverage gate: `make coverage-gate-strict` (75% baseline + ratchet) | 0.5 дня | T1.5 | coverage не упал |
| **T1.7** | Финальный коммит W1 + post-v22-backlog/ запись о завершении | 0.5 дня | T1.6 | git log, .md запись |

**Стоп после W1.** Показать diff → согласование W2.

### W2 (3-5 дней) — P2.3 CircuitBreaker консолидация

| ID | Задача | Трудоёмкость | Зависимости | DoD |
|----|--------|:------------:|-------------|-----|
| **T2.1** | Аудит callsites: какой API реально используется (по 5+ файлам) | 1 день | — | таблица callsite count per module |
| **T2.2** | Выбор канонического (предположительно `core/resilience/decorators.py` от V22.10.2 wave 1) | 0.5 дня | T2.1 | обоснование в `.hermes/plans/S38_W2_CB_choice.md` |
| **T2.3** | Deprecation: `DeprecationWarning` в остальных 4 модулях + `post-v22-backlog/cb-deprecation.md` | 1-2 дня | T2.2 | warnings + re-exports |
| **T2.4** | Тесты: 0 регрессий, новые тесты на backwards-compat | 1 день | T2.3 | `make test` зелёный |

**Стоп после W2.** Показать diff → согласование W3.

### W3 (3-5 дней) — P2.4 RateLimit консолидация

| ID | Задача | Трудоёмкость | Зависимости | DoD |
|----|--------|:------------:|-------------|-----|
| **T3.1** | Аудит callsites для rate_limit (4+ реализации) | 1 день | — | таблица |
| **T3.2** | Выбор канонического (предположительно `infrastructure/resilience/unified_rate_limiter.py`) | 0.5 дня | T3.1 | обоснование |
| **T3.3** | Deprecation + re-exports | 1-2 дня | T3.2 | warnings + tests |
| **T3.4** | Тесты на backwards-compat | 1 день | T3.3 | зелёные |

**Стоп после W3.** Согласование W4 (Groovy DSL).

### W4-W5 — ~~P7 Groovy DSL P1~~ ОТМЕНЕНО

**Причина отмены:** параллельный процесс уже реализует P7 (см. untracked файлы
`src/backend/dsl/builders/collection.py`, `src/backend/dsl/engine/processors/eip/collection.py`,
`tests/unit/dsl/engine/processors/eip/`). Не дублируем работу.

**Что остаётся в V23+ backlog (не наш scope):**
- P4 Consul — параллельный процесс
- P7 Groovy DSL P1 (4 процессора) — параллельный процесс
- P9 Groovy DSL P2+P3 (9 процессоров) — после P7
- P8 ConvertersMixin cleanup (removal) — S19 deprecation, V24+ removal

**Стоп после W3.** Согласование S39 planning (если будут новые эпики).

## Риски и митигации

| Риск | Вероятность | Митигация |
|------|:-----------:|-----------|
| **Features.py декомпозиция сломает импорты** (2804 LOC, много callsite) | 🟠 high | Поэтапно по доменам, backwards-compat через re-exports, coverage gate |
| **CB/RateLimit deprecation сломает production config** | 🟡 med | DeprecationWarning (не удаление), V24+ — actual removal |
| **Untracked M-файлы в working tree** (чужие изменения) | 🟠 high | Только `git add <конкретные_файлы>`, не `git add -A` |
| **Graphify pre-commit hook задержит** | 🟢 low | `--no-verify` (известное правило) |
| **Coverage gate провалится после рефакторинга** | 🟡 med | Baseline-aware gate, постепенный ratchet |

## Метрики успеха S38

| Метрика | Baseline | Target S38 | Как измерить |
|---------|:--------:|:----------:|--------------|
| `features.py` LOC | 2804 | <500 (декомпозиция на 5+ модулей) | `wc -l` |
| CB реализаций (canonical) | 5+ | 1 + 4 deprecated | `grep -rln class.*Breaker` |
| RateLimit реализаций (canonical) | 4+ | 1 + 3 deprecated | `grep -rln class.*RateLimit` |
| Pre-prod-check | 38/38 | 38/38 (0 регрессий) | `make pre-prod-check` |
| Noqa-директив | 1677 | 1677 или меньше | `grep -rn '# noqa' src tests | wc -l` |
| Coverage | 83% target | ≥83% (sustain) | `make coverage-gate-strict` |

## Процесс ревью (обязательно)

Перед каждым `git commit` — **8-шаговый процесс из `requesting-code-review`**:

1. `git diff --cached` — посмотреть что коммитим
2. **Static security scan** — hardcoded secrets, SQL injection, shell injection, eval/exec
3. **Baseline tests + lint** — `make lint && make type-check && make test` ДО коммита
4. **Self-review checklist** — no debug, no commented code, has tests
5. **Independent reviewer subagent** — `delegate_task` с JSON-вердиктом
6. **Evaluate** — passed/failed
7. **Auto-fix loop** (max 2 attempts) — если failed
8. **Commit** — `git commit -m "[verified] <description>"` (с `--no-verify` для graphify)

**Если ревью failed** → НЕ коммитим, чиним, повторяем цикл.

## Открытые вопросы (нужны решения Ivan)

1. **W1 (features.py):** какие домены выделяем? Моя рекомендация: auth/resilience/ai/infra/experimental (5 модулей). Альтернатива: 3 модуля (auth, infra, experimental).
2. **W2 (CB):** канонический = `core/resilience/decorators.py`? Или иной выбор после аудита callsite?
3. **W3 (RateLimit):** канонический = `infrastructure/resilience/unified_rate_limiter.py`? Или иной?
4. **W4-W5 (Groovy DSL):** включаем в S38 или переносим в S39 целиком?
5. **Pre-prod-check baseline:** использовать существующий gate или сделать новый под S38?

## Что НЕ делаем в S38

- ❌ P4 Consul — нужна инфра-решение
- ❌ P9 Groovy DSL P2+P3 (9 процессоров) — после P7
- ❌ P5 Docker Compose — V22 на K8s Helm
- ❌ P8 ConvertersMixin cleanup (removal) — S19 deprecation, V24+ removal
- ❌ Большие рефакторинги, не указанные в плане (защита от overengineering)
- ❌ Изменения в lock-файлах (Sprint 36 правило)
- ❌ Force-push, reset --hard

---

**Автор плана:** Ivan (orchestrator) | **Дата:** 2026-06-02
**Следующий шаг:** согласование с Ivan, старт W0 → T0.1 (AGENTS.md fix)
