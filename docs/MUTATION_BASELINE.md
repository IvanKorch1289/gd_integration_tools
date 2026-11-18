# Mutation Testing Baseline Report

**Обновлено:** 2026-11-18 (волна 34) · **Инструмент:** mutmut 3.7.0 (`python -m mutmut`)

## Статус: ACTIVE — гейт рабочий, fail-closed

Волна 33 разблокировала гейт (ADR-0452): были починены обвязка (бинарник
`mutmut` не в PATH, рассинхрон рабочей копии `mutants/`, ошибки сбора из-за
optional-зависимостей). Волна 34 (ADR-0452, доработка) закрыла **честность**
гейта: до неё «зелёный» статус гейта мог означать «прогон не состоялся».

### Что было сломано (найдено и исправлено в волне 34)

| Дефект | Механизм | Исправление |
|---|---|---|
| Fail-open на устаревших данных | `mutmut export-cicd-stats` при отсутствии результатов печатает «No previous mutation data found» и выходит с кодом 0, **не перезаписывая** stats-файл → гейт сравнивал score прошлого прогона | stats-файл удаляется перед экспортом; устаревшая статистика → SKIPPED с причиной |
| Кэш вердиктов стирался | `rsync --delete` удалял `mutants/**/*.meta` → каждый прогон с нуля (холодный ≈ 8–9 мин вместо тёплых 80 с) | `rsync --exclude=*.meta` |
| Бинарник не в PATH | wrapper звал `mutmut` из PATH (там только `.venv/bin/mutmut`) | `sys.executable -m mutmut` |
| Битый baseline → тихий fallback | при нечитаемом baseline подставлялось 55.0 % | явная ошибка |
| CI-шаг без таймаута | падение job на каждом PR | на момент волны 34: `timeout-minutes: 6`, `MUTATION_GATE_TIMEOUT=240`; волной 35 — отдельный job `mutation` (`timeout-minutes: 45`, `MUTATION_GATE_TIMEOUT=2280`) |
| Обёртка не работала с mutmut 3.x | флагов `--use-coverage/--coverage-data-file` больше нет, `mutmut results` не печатает score → score всегда 0 | `tools/run_mutation_tests.sh` переписан под 3.x |
| Нулевой score маскировался как измерение | нет тестов / прерванный прогон → score 0.0 % | SKIPPED с явной причиной |

### Контракт гейта

| Код | Значение |
|---|---|
| 0 | PASS — score ≥ порога из baseline |
| 1 | FAIL — score ниже порога (блокирует PR) |
| 2 | SKIPPED — score не измерен (причина в выводе шага) |
| 3 | ERROR — ошибка запуска гейта |

Порог берётся из `.baselines/mutation.json` (single source of truth): гейт
требует «не хуже baseline». SKIPPED — **не** «зелёный» результат и не
маскируется под PASS: CI-шаг печатает warning и не блокирует PR, но и не
выдаёт ложного подтверждения.

### Запуск

```bash
.venv/bin/python tools/checks/check_mutmut.py --help
.venv/bin/python tools/checks/check_mutmut.py --timeout 900   # полный прогон
.venv/bin/python tools/checks/check_mutmut.py --no-run         # по накопленным .meta
.venv/bin/python tools/checks/check_mutmut.py --update-baseline
make mutation-gate                                             # CI-цель (порог из baseline)
```

### CI-контур (волна 35, 2026-11-18)

Мутационный гейт вынесен в **отдельный job** `mutation` в
`.github/workflows/lint.yml` (общий job лимитировал шаг общим таймаутом, и
мутационный шаг не успевал выполняться):

* `timeout-minutes: 45` на job, `MUTATION_GATE_TIMEOUT=2280` на шаг гейта;
* **кэш `mutants/`** через `actions/cache` — вердикты по мутациям
  (`mutants/<path>.meta`) переиспользуются между прогонами; ключ кэша
  зависит от набора мутируемых модулей и тестов, поэтому при изменении
  кода/тестов кэш инвалидируется и вердикты пересчитываются;
* контракт exit-кодов разобран по веткам: PASS → notice + строка в
  job summary, FAIL → error (workflow красный), SKIPPED → **warning** +
  «НЕ ИЗМЕРЕНО» в job summary, ERROR → error с кодом.
* Тёплый прогон (кэш сохранён) — ≈ 80 с; холодный — ≈ 8–9 минут (в CI —
  до часа с поправкой на xdist и cold cache).

### Известные ограничения

* **Холодный прогон — самый дорогой сценарий.** Полный прогон мутаций
  занимает ≈ 8–9 минут локально и дольше на CI-раннере; в CI гейт вынесен в
  отдельный job с увеличенным таймаутом и кэшем `mutants/`, поэтому
  ограничение «SKIPPED из-за нехватки времени» больше не является штатным
  режимом. SKIPPED по-прежнему не маскируется под PASS.
* `mutants/` (~294 МБ) — локальный кэш вердиктов, в git не попадает; стирать
  его нельзя (см. дефект с `rsync --delete`).
* `also_copy = [".env"]` копирует `.env` в `mutants/` — локально и в
  gitignored-каталоге; секреты в репозиторий не попадают.

### Baseline

Текущее значение и история ratchet'а — `.baselines/mutation.json`.
Score зависит от набора мутируемых модулей (`[tool.mutmut].source_paths` в
`pyproject.toml`): изменение набора **обязательно** требует пересчёта
baseline.

## Связанные документы

* `docs/adr/0452-mutation-gate-unblocked.md` — решение по разблокировке.
* `tools/checks/check_mutmut.py` — гейт; `tools/checks/run_mutmut.py` — обвязка.
* `tools/run_mutation_tests.sh` — shell-обёртка.
