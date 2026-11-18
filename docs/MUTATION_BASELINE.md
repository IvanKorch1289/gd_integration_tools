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
| CI-шаг без таймаута | падение job на каждом PR | `timeout-minutes: 6`, `MUTATION_GATE_TIMEOUT=240` |
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

### Известные ограничения

* **Холодный прогон не укладывается в CI-бюджет.** Полный прогон мутаций
  занимает ≈ 8–9 минут, а шаг в `.github/workflows/lint.yml` ограничен
  240 с → в CI гейт честно даёт SKIPPED. Тёплый прогон (кэш `mutants/*.meta`
  сохранён) — ≈ 80 с. Для настоящего enforcement в CI нужен отдельный job с
  таймаутом ~15 мин **или** кэш `mutants/` между прогонами.
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
