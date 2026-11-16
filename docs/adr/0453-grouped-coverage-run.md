# ADR-0453 — Coverage по группам + `coverage combine`

* Статус: Accepted (2026-11-17, волна 33)
* Cycle: 189 (волна 33)
* Связан с: ADR-0443 (пороги гейтов из baseline)
* Затрагивает: `tools/run_coverage_grouped.sh`, `.github/workflows/test.yml`, `make/quality.mk`

## Контекст

Coverage-прогон считался одним монолитным `pytest tests --cov=src/backend`
(24k тестов, ~45 мин). На dev-box он **упирается в память** (OOM при
накоплении артефакта покрытия) → перемерить coverage локально нельзя, и
baseline (74 %) оставался от прогона с 206 упавшими тестами.

## Решение

* `tools/run_coverage_grouped.sh` — прогон по группам (подкаталоги `tests/`
  и `tests/unit/`, затем модули верхнего уровня `tests/unit/*.py`); части
  покрытия пишутся в отдельные файлы (`COVERAGE_FILE`), затем объединяются
  `coverage combine` и генерируется `coverage.xml`.
* Один источник правды для CI и локальной команды: CI вызывает тот же скрипт
  (`make coverage-grouped` → `tools/run_coverage_grouped.sh`).
* Итоговая цифра сопоставима с монолитным прогоном (те же тесты, тот же
  `--cov=src/backend`), но память ограничена размером группы.

## Последствия

* coverage перемеривается локально и в CI без OOM;
* baseline обновляется осознанно (`--update-baseline` у coverage-гейта);
* время прогона растёт (старт pytest на группу) — приемлемо для CI.
