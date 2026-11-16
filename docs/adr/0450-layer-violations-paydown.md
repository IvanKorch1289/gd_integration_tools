# ADR-0450 — План погашения межслойных нарушений (41 → 0) с рэтчетом

* Статус: Accepted (2026-11-17, волна 33)
* Cycle: 189 (волна 33)
* Связан с: ADR-0348 (baseline межслойных нарушений), ADR-0284 (матрица слоёв), ADR-0430 (caller-aware capability)
* Затрагивает: `tools/check_layers.py`, `.baselines/` (baseline слоёв), `src/backend/{core,services,entrypoints,infrastructure,dsl}/**`

## Контекст

`check_layers.py --strict` показывает 41 нарушение матрицы слоёв:

| Группа | Нарушений | Суть |
|---|---|---|
| `core/ → services/` | 5 | ядро импортирует сервисы (AI-gateway, guardrails, authorization) |
| `dsl/ → extensions/` | 6 | DSL-регистрация тянет бизнес-расширения |
| `entrypoints/ → extensions/` | 18 | HTTP-эндпоинты импортируют схемы/сервисы расширений напрямую |
| `services/ → extensions/` | 3 | сервисы знают о расширениях |
| `infrastructure/ + workflow/ → dsl/` | 3 | инфраструктура/раннер знают о DSL |
| `services/ → dsl/` | 5 | сервисы знают о DSL |

Часть нарушений — **композиционный** код (регистрация действий, сборка
роутов), где прямой импорт расширений — сознательное исключение
(ADR-0284: extensions регистрируются в composition root). Остальные —
настоящие инверсии: бизнес-логика расширений протекает в core/entrypoints.

## Решение

1. **Рэтчет вместо разового большого рефакторинга.** Baseline слоёв
   фиксирует текущие 41 нарушение; гейт блокирует **новые**. Каждая волна
   сокращает baseline (ADR-0348).
2. **Инверсия по доменам** — целевая архитектура:
   * `core/ → services/`: общие контракты (Protocol) переносятся в `core/`,
     реализация остаётся в `services/`, регистрация — в composition root;
   * `entrypoints/ → extensions/`: эндпоинты обращаются к действиям через
     `ActionHandlerRegistry` (уже есть `dsl/commands/action_registry.py`),
     а не к сервисам расширений напрямую;
   * `services/ → extensions/` и `→ dsl/`: плагин-регистрация переносится в
     composition root (`plugins/composition/setup*`), сервисы работают через
     core-контракты;
   * `infrastructure/ + workflow/ → dsl/`: `Exchange`/регистры дублируются в
     `core/` как Protocol.
3. **Безопасность каждого шага:** атомарный коммит на одну группу, после
   каждого — `check_layers --strict`, целевые тесты и полная регрессия.

## Последствия

* Baseline межслойных нарушений уменьшается от 41 к 0 шаг за шагом; CI
  блокирует рост уже сейчас.
* Начинать следует с `services/ → dsl/` (5 нарушений, локальные правки) и
  `infrastructure/ + workflow/ → dsl/` (3) — они не затрагивают публичные API.
* Группы `entrypoints/ → extensions/` (18) — самые крупные: перевод
  эндпоинтов на action-реестр (ADR-0284 V22), отдельными волнами.
