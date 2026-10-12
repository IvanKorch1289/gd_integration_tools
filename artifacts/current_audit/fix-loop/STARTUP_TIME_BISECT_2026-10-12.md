# STARTUP-TIME-2026-10-12 — расширенное расследование (bisect)

**Дата снятия:** 2026-10-12
**Baseline:** `.baselines/startup-time.json` — `total: 1.65` (refreshed 2026-09-28)
**Regression limit:** 2.145s (baseline × 1.3)

## Краткое резюме

| Момент | TOTAL (median of 3) | Δ от baseline 1.65s |
|---|---:|---:|
| `f681c4ed7` (DSLBuilderService facade) | **2.332s** | +0.682s (41 %) |
| `22f7ac14c` (httpx eager-import fix) | **2.410s** | +0.760s (46 %) |
| `cee4c33e5` (set measured baseline 52.25%) | **2.404s** | +0.754s (46 %) |
| `e91fb91fe` (fix(observability)) | **2.415s** | +0.765s (46 %) |
| `4baf3a345` (fix(coverage) restore gate) | **2.429s** | +0.779s (47 %) |
| `cf0802244` (audit revision) | **2.474s** | +0.824s (50 %) |
| 8 audit-коммитов поверх | 2.450s | +0.800s (48 %) |

**Все точки выше baseline 1.65s** — даже на commit, на котором baseline
был зафиксирован (`cee4c33e5`). Это значит: baseline измерялся
**в других условиях**, а не отражает реальный cold-import текущего кода.

## Где случился реальный регресс

За пределами bisect-окна (до `4baf3a345`). Baseline.json
комментарий: «baseline 1.304 (2026-08-31) устарел: 4 спринта фич
+ httpx eager-импорт в constants.py (устранён, 22f7ac14c)».
То есть ДО `22f7ac14c` было ещё хуже (с eager import — >1.65s).
После фикса — должно было стать лучше, но в нашей среде
всё равно 2.3-2.5s.

**Гипотеза**: baseline 1.65s замерялся на другой машине (или в
pre-prod с прогретым кэшем), а на этой dev-сессии startup
стабильно 2.3-2.5s. Это ENVIRONMENTAL difference, а не regression
конкретного коммита.

## Подтверждение: 8 audit-коммитов не привнесли регресс

8 audit-коммитов поверх `cf0802244` (1a01efd07 ... 78a45cc3b):
- `cf0802244` baseline: 2.474s
- HEAD (`78a45cc3b`): 2.450s
- **Δ = -0.024s (≈ 0)** — вариация в пределах ±0.05s.

Это значит:
- Регресс **не из audit-коммитов**.
- Регресс **pre-existing** для всей post-`4baf3a345` истории.
- Причины — environmental (dev-сессия) или cumulative code growth
  до `4baf3a345`, не за последние 5-15 дней.

## Что делать

Baseline **не отражает реальность** в этой среде. Это policy-вопрос:

1. **Refresh baseline** через ручной `uv run python tools/checks/startup_time.py
   --ratchet` → `--ratchet` ТОЛЬКО уменьшает baseline, поэтому
   не поможет (текущее 2.45s > 1.65s, baseline может только
   опуститься, не подняться). Нужен MANUAL update: edit
   `.baselines/startup-time.json` напрямую с новым значением + ADR.

2. **Investigation**: bisect ДО `4baf3a345` — найти коммит, который
   впервые вытащил startup выше 2.0s. Это много bisect-итераций
   (~10-15) по 1-2 минуты каждая = 15-30 минут. В scope этого
   аудита не входит.

3. **Документировать** как pre-existing environmental issue, оставить
   как OPEN с пометкой «требует manual baseline refresh + ADR».

**Решение**: оставить как OPEN (вариант 3). Документация — здесь
и в §14 финального отчёта.

## Verdict

**REJECTED AS STALE для audit-коммитов** (как и раньше, но с
большей уверенностью). Baseline 1.65s заведомо не отражает реальность
этой среды. Требует policy-решения: refresh baseline (manual + ADR)
или environmental standardisation.
