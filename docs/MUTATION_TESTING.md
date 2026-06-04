# Mutation Testing — gd_integration_tools

Sprint 39 W4 · v15 §11 · branch coverage 38% → 55% via real mutation analysis.

## Зачем

Line/branch coverage показывает *какой код выполнился*, но не *проверен ли он*.
Тест, который вызывает `breaker.allow_request()` и не проверяет возвращаемое
значение, даёт 100% line coverage, но бесполезен: мутация, заменяющая
`return True` на `return False`, его не убьёт.

**Mutation testing** отвечает на другой вопрос: *сколько ошибочных вариантов
нашего кода наши тесты способны обнаружить*? Инструмент вводит точечные
изменения (operator swaps, constant tweaks, name mutations) и проверяет, что
хотя бы один тест падает. Мутация, которую никто не убил — это упущенный
тест-кейс.

Per v15 §11: 55% mutation score на hot-модулях соответствует реальной защите
от регрессий, а не поверхностной branch coverage.

## Стек

| Компонент | Выбор | Обоснование |
|-----------|-------|-------------|
| Tool      | [mutmut 2.4.4](https://mutmut.readthedocs.io/) | Лёгкий (1 dep), coverage-guided, чистый CLI |
| Runner    | pytest 9.0.3 (уже в проекте) | Не вводим новый test-runner |
| Coverage  | coverage 7.14.1 (уже в проекте) | `--use-coverage` фильтрует релевантные тесты |
| Альтернатива | cosmic-ray | Тяжелее (operator DB, requires sqlite), отвергнут для S39 W4 |

## Установка

```bash
.venv/bin/python -m pip install "mutmut==2.4.4"
```

## Как запустить

Базовый прогон (3 hot-модуля: `FeatureFlags`, `RouteBuilder`, `CircuitBreaker`):

```bash
./scripts/run_mutation_tests.sh
# или напрямую:
.venv/bin/python -m mutmut run --use-coverage --coverage-data-file=.coverage.mutations
```

Подкоманды обёртки:

```bash
./scripts/run_mutation_tests.sh run        # полный прогон + gate check
./scripts/run_mutation_tests.sh results    # сводка (killed / survived / timeout)
./scripts/run_mutation_tests.sh html       # детальный HTML-отчёт → mutants/html/
./scripts/run_mutation_tests.sh quick      # smoke-run для CI dry-check
./scripts/run_mutation_tests.sh clean      # сбросить .mutmut-cache и mutants/
```

Переменные окружения:

```bash
MUTMUT_MIN_SCORE=60.0 ./scripts/run_mutation_tests.sh   # переопределить gate
MUTMUT_TIMEOUT=120  ./scripts/run_mutation_tests.sh     # увеличить per-mutation timeout
```

## Интерпретация результатов

После прогона `mutmut results` печатает таблицу:

```
Legend:
  Killed     : мутация поймана хотя бы одним тестом
  Survived   : мутация НЕ поймана — упущенный тест-кейс
  Timeout    : тесты зависли (>60s) — нестабильная мутация, проверить вручную
  Skipped    : мутация в ignore-паттерне (.mutmut-ignore) — by design
  Suspicious : pytest вернул error вместо failed — flaky test

Mutation score = Killed / (Killed + Survived + Timeout + Suspicious)
```

**Score = 55%** означает: на каждые 100 ошибочных вариантов нашего кода наши
тесты ловят 55. Остальные 45 — реальные пробелы в покрытии.

### Категории «survived» мутаций

1. **Boundary off-by-one** (`>` → `>=`, `+1` → `+0`): нет теста, проверяющего
   граничное значение. Добавить: `assert result == expected_for_n_items`.
2. **Boolean swap** (`True` → `False`): нет negative-test. Добавить:
   `assert not condition_when_X_is_disabled`.
3. **Constant tweak** (`0` → `1`, `"INFO"` → `"DEBUG"`): нет проверки на
   конкретное значение. Добавить: `assert log.level == "INFO"`.
4. **Method rename / call removal**: метод, который не вызывается ни в одном
   тесте — кандидат на удаление или на нетривиальный indirect call (dependency
   injection, event hook). Добавить: интеграционный тест.

## Связь с branch coverage

| Branch coverage | Mutation score | Интерпретация |
|-----------------|----------------|---------------|
| < 30%           | < 20%          | Тесты — smoke-набор, не защищают код |
| 30–50%          | 20–35%         | Базовое покрытие, много happy-path-only тестов |
| 50–70%          | 35–55%         | **S39 W4 target** — рабочая защита критических путей |
| 70–90%          | 55–75%         | Production-grade (S40+) |
| > 90%           | > 75%          | Параноидальный уровень (требует property-based тестов) |

Branch coverage измеряет *какие ветки if/else выполнились*; mutation score
измеряет *сколько ошибочных вариантов тесты отвергают*. Разрыв между ними
— это тесты, которые покрывают строки, но не имеют assertions на их значения.

## Расширение scope

При добавлении нового hot-модуля в `paths_to_mutate`:

1. Убедиться, что у модуля есть unit-тесты в `tests/unit/<path>/`.
2. Добавить путь в `pyproject.toml` → `[tool.mutmut] paths_to_mutate`.
3. Добавить `tests_dir` (если тесты в новой директории).
4. Запустить `./scripts/run_mutation_tests.sh` — замерить baseline score.
5. Довести до ≥ 55% (или обновить `minimum_score` в `pyproject.toml`,
   согласовав с командой).

## CI интеграция

Предлагаемый pre-merge check (вне scope S39 W4):

```yaml
# .github/workflows/mutation.yml
mutation:
  runs-on: ubuntu-latest
  steps:
    - uses: actions/checkout@v4
    - uses: actions/setup-python@v5
      with: { python-version: "3.13" }
    - run: pip install mutmut==2.4.4
    - run: ./scripts/run_mutation_tests.sh
```

Время прогона: 3–5 минут для текущих 3 модулей; масштабируется линейно.

## Гигиена

В `.gitignore` должны быть (добавить отдельно — вне scope этой задачи):

```
.mutmut-cache
mutants/
.coverage.mutations
.mutmut-ignore.bak
```

## Troubleshooting

**`No module named mutmut`** — `pip install mutmut==2.4.4` внутри `.venv`.

**`No tests to run` для мутации** — тест не покрывает эту строку. Проверить
`coverage report --include=src/backend/core/resilience/breaker.py`.

**Все мутации timeout'ят** — уменьшить `MUTMUT_TIMEOUT` или починить hang
в тестах (`pytest --timeout=10` для диагностики).

**Score скачет ±10% между прогонами** — flaky tests. Запустить
`pytest -p no:randomly --count=3` на целевом модуле.

## Где это в плане

- `PLAN.md` V22 §11 — обоснование 55% gate.
- `Makefile` — таргет `make mutation` (добавить в S40, отдельной задачей).
- `docs/RAG_INGEST.md` — этот файл индексируется в `project_docs` для RAG.
