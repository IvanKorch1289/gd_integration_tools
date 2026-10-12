# Startup-time regression — pre-existing, не из audit-коммитов

**Дата снятия:** 2026-10-12
**Baseline:** `.baselines/startup-time.json` — `total: 1.65` (refreshed 2026-09-28)
**Regression limit:** 2.145s (baseline × 1.3)

## Замер

| Момент | TOTAL (median of 3) | Сэмплы |
|---|---:|---|
| HEAD (8 audit-коммитов поверх `cf0802244`) | **2.450s** | 2.467, 2.299, 2.450 |
| HEAD~1 (= `cf0802244`, audit-ревизия) | **2.474s** | 2.474, 2.451, 2.507 |
| Разница | **-0.024s** (≈ 0) | — |

**8 audit-коммитов (1a01efd07, c86ca0424, 890effb46, d2c5a4d75, 003e5e6b8,
31ac7ddbf, 528fd01d0, 14cf8195b) добавили к startup-time ≈ 0 секунд.**

## Где реально случился регресс

Baseline `1.65s` зафиксирован `2026-09-28` (justification: «1.304 устарел;
4 спринта фич + httpx eager-импорт в constants.py (устранён, 22f7ac14c).
Тихий standalone cold-import: 1.511-1.648s; внутри pre-prod suite
1.7-1.9s»). Уже на следующий день (`cf0802244` родился в
`2026-10-09 16:36`) реальный standalone TOTAL был `2.474s` —
**+0.8s сверх baseline сразу после refresh-а**.

Кто/что добавило +0.8s между 2026-09-28 и 2026-10-09 — за пределами
этого аудита; коммиты `cf0802244` (services/dsl_portal → dsl/portal)
и `13906afdf` (feat(layers): split baseline) — два подозреваемых
кандидата. `git log --oneline --since=2026-09-28 --until=2026-10-09`
даст полный список, но атрибуция к конкретному коммиту — отдельный
профиль-задача (запустить startup_time.py на каждом коммите).

## Корректный фикс

`make doctor` сейчас показывает `[✗] startup-time REGRESSION LIMIT`,
но **это pre-existing failure, не блокер моих коммитов**. Три варианта
реакции (все требуют ADR, т.к. baseline — single source of truth
для гейта):

1. **Investigate** — bisect между `cf0802244` (2.474s) и
   baseline-коммитом 2026-09-28, найти виновника, откатить/rework
   его, вернуть startup до baseline.
2. **Refresh baseline** через manual `uv run python tools/checks/startup_time.py --ratchet` —
   НЕ, `--ratchet` растёт только вниз, manual нужен. Обоснование:
   «baseline 1.65 занижен; фактически холодный старт с 2026-09-28
   2.4-2.5s; refresh до 2.5s, regression limit пересчитать в
   .baselines/startup-time.json».
3. **Оставить как есть** — `make doctor` будет падать до тех пор,
   пока кто-то не разберётся.

## Почему это не блокирует audit

- `make lint-strict` exit 0
- `make type-check-budget` exit 0 (2 ≤ 5)
- `make cve-gate` exit 2 (честный fail: `deepteam==1.0.9` не ставится на py3.14)
- `make doctor` exit 1, summary 8/9 OK — mypy-budget TIMEOUT auto-resolved
  коммитом `14cf8195b`; startup-time остаётся единственным FAIL,
  pre-existing.

## Рекомендация для следующего шага

Открыть отдельную задачу: «Investigate startup-time regression
2026-09-28 → 2026-10-09 (baseline 1.65 → 2.47s, +50%)». До её
закрытия `make doctor` будет падать; `make ci` (для разблокировки
gate-а) не зависит от `make doctor`, поэтому CI-blocking риск
нулевой.
