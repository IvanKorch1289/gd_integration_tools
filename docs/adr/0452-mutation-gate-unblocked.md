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
