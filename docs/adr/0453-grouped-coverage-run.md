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

## Уточнение волны 33 (2026-11-16): скрипт был нерабочим

Первая версия скрипта **не мог завершиться ни разу** (проверено прогонами):

| Дефект | Симптом | Исправление |
|---|---|---|
| имя части покрытия | `coverage combine` ищет `<dir>/.coverage.*`, части назывались `<name>.coverage` | части называются `.coverage.<group>` |
| порог на группе | `fail_under = 70` из pyproject применялся к каждой группе → группа красная при зелёных тестах | `--cov-fail-under=0` на группе, итоговый порог — на объединённом отчёте |
| пустые группы | каталог без собираемых тестов → pytest exit 5 (`no tests ran`) | exit 5 трактуется как «пропуск», не как ошибка |
| `tests/chaos` | нет `pytest-toxiproxy` (нет в lock) → «fixture not found» | исключён (свой workflow `chaos.yml`) |
| `tests/integration` | требует живых PostgreSQL/Redis/браузеров | исключён (часть — в `sentinel-integration.yml`) |
| stale `.coverage` | старый артефакт монолитного прогона смешивался с частями | `rm -f .coverage` перед combine |

То есть до исправления CI-джоб `test.yml` не доходил до coverage-гейта: шаг
`Run pytest with coverage (grouped)` падал, `coverage.xml` не создавался,
следующий шаг гейта не выполнялся.

## Последствия

* coverage перемеривается локально и в CI без OOM;
* baseline обновляется осознанно (`--update-baseline` у coverage-гейта);
* время прогона растёт (старт pytest на группу) — приемлемо для CI;
* **сфера прогона**: hermetic-сьюты (`tests/unit/**` + верхнеуровневые
  `auth/cache/core/e2e/observability/resilience/scheduler/webhook`).
  Сьюты с внешними сервисами (`chaos`, `integration`) и с optional-плагинами
  (`perf` — нужен `pytest-benchmark`) исключены осознанно: в CI их нет;
  pre-existing падения `tests/{property,security,smoke,tools,workflow}`
  (вне CI-скоупа) зафиксированы в роевом отчёте волны 33.

## Уточнение волны 34 (2026-11-18) — перемер выполнен, baseline переведён на метрику гейта

Документ фиксирует решение на момент принятия (волна 33). Факт:

* grouped-прогон переведён в канонический CI-режим (`-n 2 --dist loadfile`) —
  на dev-box 4 воркера давали OOM;
* **прежние 74 % были branch-числом**, а гейт `tools/check_coverage_gate.py`
  сравнивает **line-rate** из `coverage.xml` — baseline и гейт мерили разное.
  Baseline приведён к единой метрике гейта;
* перемер: **77.68 %** line-rate (branch 75 %) → `.baselines/coverage.json`
  (`coverage_percent: 77.68`, `threshold: 70.0`, `target_threshold: 75.0`);
* цель рэтчета «75 %» (S19 K2 W4) **достигнута** — следующая цель 78 %;
* логи прогона: `.run/coverage-baseline-2026-11-17/`.

Контекст «74 % оставался от прогона с 206 упавшими тестами» в разделе
«Контекст» выше остаётся верным как описание причины решения — это история,
а не текущее значение baseline.
