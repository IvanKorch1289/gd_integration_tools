# ADR-0452 — Mutation-гейт разблокирован и переведён на рэтчет

* Статус: Accepted (2026-11-17, волна 33)
* Cycle: 189 (волна 33)
* Связан с: ADR-0285 (baseline-подход), ADR-0443 (пороги гейтов из baseline)
* Затрагивает: `tools/checks/check_mutmut.py`, `tools/checks/run_mutmut.py`, `.baselines/mutation.json`, `.github/workflows/lint.yml`, `docs/MUTATION_BASELINE.md`

## Контекст

Mutation-гейт был заблокирован с 2026-06-04 (`docs/MUTATION_BASELINE.md`):
361 ошибка сбора тестов. Повторная проверка показала, что блокер был не в коде,
а в обвязке:

1. **Бинарник `mutmut` не в PATH** — гейт звал `mutmut run`, а в venv есть
   только модуль (`python -m mutmut`);
2. **Рабочая копия мутантов не обновлялась** — в `mutants/` оставались
   удалённые тесты (`test_cache_namespace.py` → `ModuleNotFoundError`) и
   отсутствовали `deploy/`, `config/`, `config_profiles/`, `docs/`, `extensions/`,
   `routes/`, `ops/`, `.env.example`, которые читают тесты;
3. Ошибки сбора тестов из-за отсутствующих optional-зависимостей — к текущему
   моменту зависимости установлены, сборка проходит.

## Решение

* гейт вызывает `python -m mutmut` (не PATH-бинарник);
* wrapper синхронизирует в `mutants/` не только `src/`, но и `tests/`,
  `deploy/`, `config/`, `config_profiles/`, `docs/`, `extensions/`, `routes/`,
  `ops/` и `.env.example` (`rsync --delete` + копирование файла);
* **порог берётся из baseline** `.baselines/mutation.json` (рэтчет «не хуже
  baseline»), а не из константы в коде; `--update-baseline` фиксирует новое
  значение;
* гейт включён в CI (`lint.yml`).

## Последствия

* Первый рабочий замер: **21.6 %** (мутируются 10 security-critical модулей) —
  это и есть baseline; рост возможен только с новыми тестами;
* дефект инфраструктуры гейта (заблокирован с 2026-06-04) закрыт;
* `docs/MUTATION_BASELINE.md` обновлён: статусбольше не  BLOCKED.

## Уточнение волны 34 (2026-11-18) — гейт переведён в fail-closed

Документ фиксирует решение на момент принятия (волна 33). Волна 34 изменила
**честность** гейта: до неё «зелёный» статус мог означать «прогон не
состоялся». Найдено и исправлено 7 дефектов обвязки:

* fail-open на устаревших stats-файлах (`mutmut export-cicd-stats` при
  отсутствии результатов выходит с кодом 0 и **не перезаписывает** stats-файл)
  → stats-файл удаляется перед экспортом, устаревшая статистика → SKIPPED;
* **`rsync --delete`** (из решения выше) стирал кэш вердиктов `mutants/**/*.meta`
  → каждый прогон с нуля (холодный ≈ 8–9 мин вместо тёплых 80 с); заменено на
  `rsync --exclude=*.meta`;
* вызов бинарника из PATH → `sys.executable -m mutmut`;
* тихий fallback на битый baseline (подставлялось 55.0 %) → явная ошибка;
* CI-шаг без таймаута → `timeout-minutes: 6`, `MUTATION_GATE_TIMEOUT=240`;
* обёртка не работала с mutmut 3.x (флагов `--use-coverage/--coverage-data-file`
  больше нет, `mutmut results` не печатает score → score всегда 0);
* нулевой score без тестов маскировался как измерение → SKIPPED с причиной.

Контракт exit-кодов гейта: **0 = PASS, 1 = FAIL, 2 = SKIPPED (с причиной),
3 = ERROR**. Порог берётся из `.baselines/mutation.json`; SKIPPED не
маскируется под PASS.

Baseline **21.6 % переподтверждён холодным прогоном** (пустая рабочая копия
`mutants/`, без кэша вердиктов): killed 247 / total 1142. Промежуточные 17.5 %
оказались артефактом измерения (устаревшая копия `mutants/` + прерванная фаза
«clean tests»: двойной сбор модуля tenant-фильтра в рабочей копии mutmut'а
давал `Table 'am_plain' is already defined`), исправлено уникальным именем
таблицы. Подробности — `docs/MUTATION_BASELINE.md` и
`artifacts/current_audit/SWARM_READINESS_REPORT_2026-11-17.md` §2.4, §4.1.
