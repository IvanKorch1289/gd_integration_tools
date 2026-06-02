# P0 — Tests coverage gap analysis (T-P0.1)

> **S38 v9 P0: Тесты 51%→83%** (v9 §V, v9 §VI "единственный критический барьер")
> **Метод:** без `make coverage-gate` (timeout 600s, см. TECH_DEBT) —
> прямой `pytest --cov` с разумным timeout.

## Baseline (факт-чек 02.06.2026)

| Метрика | Значение | Источник |
|---------|:--------:|----------|
| `make coverage-gate` | ❌ timeout 600s | TECH_DEBT |
| `make test` (target) | ❌ не существует | `make help` |
| `make ci` (composite) | ⏳ не запускали | — |
| Coverage baseline (V22) | 50% (S34) → 75% (S19) → 83% (S20) | PLAN.md V22 |
| Coverage в V22.10.2 close | 90%+ pre-prod-check | PLAN.md V22.6 |
| Ruff errors | 394 (269 fixable) | `ruff check` |
| Noqa directives | 1677 | `grep '# noqa'` |
| Tests count | ~2700+ (по 844 .py test files) | `find tests -name '*.py' | wc -l` |

## P0 Definition of Done (v9 §VI)

| Критерий | v9 минимум | v9 цель | Текущее |
|----------|:----------:|:-------:|:-------:|
| **Покрытие строк** | 75% | 83% | неизвестно (coverage-gate не работает) |
| **Покрытие ветвей** | 60% | 70% | неизвестно |
| **God-файлов (>300)** | <50 | 0 | 166 |
| **Noqa** | <500 | <100 | 1677 |
| **CI/CD зелёный** | 100% | 100% | unknown |

## T-P0.1 — Стратегия

**Подход:** Обойти timeout через прямой `pytest --cov` + per-layer breakdown.

### Шаги

1. **T-P0.1.1**: запустить `pytest --cov --cov-report=xml --cov-report=term -x --timeout=300` с разумным timeout
2. **T-P0.1.2**: проанализировать `coverage.xml` — какие модули <50% coverage
3. **T-P0.1.3**: составить gap-report `.shared/context/P0_coverage_gap.md` (топ-20 модулей)
4. **T-P0.1.4**: предложить конкретные тесты для gap-модулей (auth, resilience — v9 §V P0)

### Почему НЕ `make coverage-gate`

- Timeout 600s (10 мин) — слишком мало для проекта с 844 test files
- `make` команда `coverage-gate` запускает pytest с coverage, но не per-layer breakdown
- Прямой `pytest --cov` даёт больше контроля (per-file, per-layer)

## T-P0.2 — Tests backlog (после gap analysis)

- Top-1 gap: добавить unit-тесты для critical модуля
- Top-2 gap: добавить integration test
- ...
- Каждый модуль: минимум 1 sanity-тест + 2-3 unit-теста

## T-P0.3 — Coverage gate (отложено)

После накопления coverage, обновить `make coverage-gate` с новым baseline.
Возможно, проблема в конкретном тесте (бесконечный цикл, deadlock).

## Что НЕ делаем

- ❌ Не делаем 100% coverage (overengineering)
- ❌ Не пишем property-based tests без обоснования (v9 §V P0 упоминает, но не приоритет)
- ❌ Не трогаем существующие тесты (если они работают)
- ❌ Не удаляем тесты для ускорения (anti-pattern)

## Следующий шаг

**T-P0.1.1** — запуск pytest --cov напрямую (минуя make coverage-gate).
