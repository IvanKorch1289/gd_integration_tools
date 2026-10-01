# library_consolidation.md — проверка «уже присутствуют, но не подключены»

**HEAD:** `3b509542e96d89d79df45200d31904cd4fa97947`
**Интерпретатор:** `/home/user/dev/gd_reaudit/.venv/bin/python` (Python 3.14.0)
**Дата замера:** 2026-10-01
**Правило:** «наличие в pyproject ≠ использование»; «mock-импорт ≠ реальная
совместимость». Статус установки проверялся через `importlib.metadata`, а не
по чтению `pyproject.toml`.

---

## Сводная таблица

| Библиотека | в pyproject | установлена | мест в src | реально работает | custom LOC замены | Вердикт |
|---|---|---|---:|---|---:|---|
| openfeature-sdk | да (extra `feature_flags`, L624) | **НЕТ** | **0** | нет | **1265** | **REJECT** |
| schemathesis | да (dev-группа, L650) | да (4.26.1) | 42 упоминания, 1 wrapper | **нет — сломано** | 231 (обёртка) | **BLOCKED** |
| testcontainers | да (L499 + L679) | да (4.13.3) | 13 импортов | **да** | 0 | **ADOPT** |
| faststream | да (**base**, L68) | да (0.7.5) | 22 импорта | **да** | 1566 (bypass) | **ADOPT** + DEFER |
| temporalio | только extras (L373/422/462/501) | **НЕТ** | 37 импортов | **нет** | 423 | **BLOCKED** |
| playwright / patchright | только extras (L247-248 и др.) | **оба НЕТ** | 4 импорта | **нет** | 0 (580 — обёртка) | **BLOCKED** |

**Итог: из шести библиотек реально работают две** — `testcontainers` и
`faststream`. Четыре заявлены, но не подключены; у `schemathesis` подключение
существует, но сломано.

---

## F-AQ10 · P1 · OpenFeature объявлен, но не используется — 1265 LOC самописной замены

| Поле | Значение |
|---|---|
| **Severity** | P1 |
| **file:line** | `pyproject.toml:624` (extra `feature_flags`); `core/feature_flags/openfeature_provider.py:104,198`; `flagsmith_provider.py`; `flagsmith_client.py` |
| **Reproduction** | `grep -rn -E "^\s*(from\|import)\s+openfeature" --include=*.py src tests tools extensions` |
| **Expected** | OpenFeature как единый feature-flag facade |
| **Actual** | `RESULT_COUNT=0` — **ни одного реального импорта** при 117 текстовых упоминаниях в докстрингах и именах классов |
| **Impact** | Зависимость в lock-файле не даёт ничего; поддерживаются две самописные реализации одного интерфейса |
| **Fix** | REJECT: собственная реализация уже имеет tenant-scoped override и Redis-broadcast, чего SDK не покрывает. Убрать из extras, чтобы не создавать ложного ожидания |
| **Regression test** | `import openfeature` в CI-bootstrap не нужен; вместо этого guard «в extras не должно быть неиспользуемых пакетов» |
| **Commit SHA** | не закоммичено |

**Custom LOC (замена SDK):**
```
 444  core/feature_flags/openfeature_provider.py
 262  core/feature_flags/flagsmith_provider.py
 205  core/feature_flags/flagsmith_client.py      # сырой HTTP-клиент к Flagsmith
  93  core/feature_flags/service.py
  68  core/feature_flags/__init__.py
 193  core/tenancy/feature_flag_scope.py
1265  итого
```
`openfeature_provider.py:104` (`InMemoryProvider`) и `:198` (`FlagsmithBackend`)
реализуют SDK-интерфейс обычными Python-классами, включая собственную
`EvaluationContext` (`:51`).

**LOC после миграции: требует измерения.** SDK заменил бы `openfeature_provider.py`
(444) и, вероятно, `flagsmith_provider.py` (262), но `flagsmith_client.py` (205),
`service.py`, `feature_flag_scope.py` — проектная логика (DB-реестр флагов,
tenant scoping), которую SDK не покрывает. Реалистичная экономия **400–700 LOC**;
точное число требует прототипа, а не оценки.

## F-AP10 · P1 · Schemathesis подключён, но runner физически не может выполниться

| Поле | Значение |
|---|---|
| **Severity** | P1 |
| **file:line** | `tools/api_fuzz_runner.py:145` (`--exitfirst`), `:186-189`; `.github/workflows/api-fuzz.yml:43,52,60` |
| **Reproduction** | `python tools/api_fuzz_runner.py --openapi http://127.0.0.1:9/openapi.json --max-examples 2 --workers 1 --report /tmp/st1.json` |
| **Expected** | fuzz-кейсы выполняются, отчёт пишется |
| **Actual** | `ERROR: Error: No such option: --exitfirst` → `EXIT_CODE=2`; `/tmp/st1.json` **не создан**; ветка `return EXIT_ERROR` срабатывает до `write_text` |
| **Impact** | API contract-fuzzing не выполняется ни разу; тесты `tests/unit/tools/test_api_fuzz_runner.py` мокают вывод, поэтому зелёные |
| **Fix** | удалить `--exitfirst` из argv (в schemathesis 4.x флага нет: `schemathesis run -h \| grep -c exitfirst` → `0`) |
| **Regression test** | `test_runner_uses_supported_schemathesis_flags` — сверять argv со списком опций установленного schemathesis |
| **Commit SHA** | не закоммичено |

**Фактический вывод:**
```
$ schemathesis --version
schemathesis, version 4.26.1
$ schemathesis run -h 2>&1 | grep -c 'exitfirst'
0
$ python tools/api_fuzz_runner.py --openapi http://127.0.0.1:9/openapi.json ...
[api-fuzz] schemathesis run http://127.0.0.1:9/openapi.json
ERROR: Usage: schemathesis run [OPTIONS] LOCATION
Error: No such option: --exitfirst
EXIT_CODE=2
$ ls -la /tmp/st1.json
ls: невозможно получить доступ к '/tmp/st1.json': Нет такого файла или каталога
```
Без флага CLI работает корректно: `SCHEMA_EXIT=1` — «Connection refused», то есть
разбор флагов проходит, падает только коннект. **Дефект изолирован в argv.**

## F-AQ11 · P1 · CI-job api-fuzz падает на `uv sync --extra dev`

| Поле | Значение |
|---|---|
| **Severity** | P1 |
| **file:line** | `.github/workflows/api-fuzz.yml:43` |
| **Reproduction** | `uv sync --extra dev --dry-run` |
| **Expected** | job доходит до шага со schemathesis |
| **Actual** | `error: Extra 'dev' is not defined in the project's 'optional-dependencies' table` → `UV_EXIT=2` |
| **Impact** | job прерывается до fuzz-шага; не блокирует PR только потому, что `continue-on-error: true` (`:25`) |
| **Fix** | `uv sync` + `--group dev` (dev — dependency-group, а не extra) либо `--extra test-all` |
| **Regression test** | meta-тест, что все `uv sync --extra X` в workflows соответствуют таблице `[project.optional-dependencies]` |
| **Commit SHA** | не закоммичено |

**Дополнительно: гейт не блокирующий ни при каких условиях.** Три независимых
причины, каждая достаточна:
1. `schemathesis_gate_enabled` default-OFF — `core/config/features/sprint6.py:167`;
2. в workflow `FEATURE_SCHEMATHESIS_GATE_ENABLED: "false"` — `api-fuzz.yml:52`;
3. бэкенд в CI не поднимается (комментарий `:49-50` — «smoke — без backend»),
   вывод глушится через `|| echo` (`:60`).

В `make ci` / `make pr` api-fuzz **не входит**: `make/pipelines.mk:22-34` его не
перечисляет, `Makefile:89` — лишь строка в `.PHONY`. То есть даже после починки
обоих дефектов гейт останется декоративным, пока не попадёт в composite.

## F-AT11 · P2 · Комментарий в `pyproject.toml` утверждает неверное о temporalio

| Поле | Значение |
|---|---|
| **Severity** | P2 (документация вводит в заблуждение при принятии решений) |
| **file:line** | `pyproject.toml:484` |
| **Reproduction** | `python -c "from importlib.metadata import version; version('temporalio')"` |
| **Expected** (по комментарию) | «temporalio уже в base deps» |
| **Actual** | `MISSING temporalio`; объявлен в `[project.optional-dependencies]` (extras `workflow` L373, `test-workflow` L422, `test-all` L462, `testkit` L501), **не** в `[project].dependencies` |
| **Impact** | 37 импортов в src считаются работающими, но в CI (`uv sync` без extras) temporalio отсутствует ⇒ 37 импортов и 7 тестов мертвы |
| **Fix** | исправить комментарий; либо перенести в base, если durable-execution обязателен в релизном контуре |
| **Regression test** | CI-bootstrap-шаг с `import temporalio`, если зависимость должна быть гарантированной |
| **Commit SHA** | не закоммичено |

**Custom LOC замены: 423** (`infrastructure/workflow/pg_runner_backend.py`) —
самописный durable-execution backend. Весь `infrastructure/workflow/` — 3826 LOC,
но значительная часть — Temporal-специфичный клей, а не замена.

Поведение при отсутствии — **жёсткий `RuntimeError`, а не деградация**
(`temporal_backend.py:149-154`, `lite_temporal_backend.py:55-58`), поэтому
Temporal-путь в этом venv недостижим целиком. Это связывается с F-AT1/F-AT2:
prod-профиль деградирует на `PgRunner`, а флаг `workflow_use_temporal` по
умолчанию `False` — то есть деградация не случайна, а спроектирована, но
не задокументирована в том виде, в котором её читает инженер.

## F-AP11 · P1 · Playwright/patchright: бинарники есть, пакетов нет, тесты исключены

| Поле | Значение |
|---|---|
| **Severity** | P1 (блокирует раздел BROWSER DoD) |
| **file:line** | `pyproject.toml:1190` (`addopts` с `--ignore`), `:247-248,442,448-449,464-465` (extras) |
| **Reproduction** | `python -c "import playwright"`; `grep -n addopts pyproject.toml` |
| **Expected** | canonical browser runtime + исполняемые browser-тесты |
| **Actual** | `MISSING playwright`, `MISSING patchright`; при этом `ls ~/.cache/ms-playwright` → `chromium-1243/ ffmpeg-1011/` |
| **Impact** | раздел BROWSER = `ENV_BLOCKED` (см. `browser_results.md`); RPA-тесты проходят за 0.10 s без запуска браузера |
| **Fix** | `uv sync --extra rpa` в канонический venv + снять `--ignore` + переписать тест в pytest-форму |
| **Regression test** | `import playwright` в CI-bootstrap; `@pytest.mark.browser`-job с реальным Chromium |
| **Commit SHA** | не закоммичено |

Точные строки:
```
pyproject.toml:1190
addopts = "-ra --strict-markers --import-mode=importlib \
          --ignore=tests/mcp/test_streamlit_via_playwright.py --ignore=tests/unit/test_main.py"
```

Поведение при отсутствии неоднородно: `browser_pool._import_runtime`
(`browser_pool.py:190-210`) корректно деградирует `patchright → playwright →
RuntimeError`; а `infrastructure/clients/transport/browser.py:69` импортирует
**без guard** → голый `ImportError` на `start()`.

Custom LOC замены: **0**. `browser_pool.py` (210) + `transport/browser.py` (370) =
580 LOC — тонкая обёртка пула/жизненного цикла **поверх** библиотеки, а не
самописная замена.

## F-AQ12 · P2 · Параллельный брокерный слой в обход faststream — 1566 LOC

| Поле | Значение |
|---|---|
| **Severity** | P2 |
| **file:line** | `infrastructure/sources/nats.py:268`, `nats_jetstream.py:280`, `sinks/nats_jetstream.py:164`, `clients/transport/nats_pool.py:153`, `cdc/debezium_events_backend.py:375`, `clients/external/cdc/kafka_strategy.py:237`, `clients/messaging/memory_broker.py:89` |
| **Reproduction** | подсчёт LOC перечисленных файлов; проверка импортов `nats-py`/`aiokafka` |
| **Expected** | faststream как единственный broker lifecycle facade |
| **Actual** | faststream работает (22 импорта, брокеры резолвятся в рантайме), **но** рядом 1566 LOC прямых клиентов в обход него |
| **Impact** | два конкурирующих пути к NATS/Kafka; риск расхождения поведения и конфигурации |
| **Fix** | DEFER: прямые клиенты выбраны ради пулинга и низкой latency в CDC; обоснование консолидации без бенчмарка дать нельзя |
| **Regression test** | — (требует бенчмарка до решения) |
| **Commit SHA** | не закоммичено |

```
 268  infrastructure/sources/nats.py                 # прямой nats-py
 280  infrastructure/sources/nats_jetstream.py
 164  infrastructure/sinks/nats_jetstream.py
 153  infrastructure/clients/transport/nats_pool.py
 375  infrastructure/cdc/debezium_events_backend.py  # прямой aiokafka
 237  infrastructure/clients/external/cdc/kafka_strategy.py
  89  infrastructure/clients/messaging/memory_broker.py  # dev-light fallback
1566  итого
```
`nats-py` 2.15.0 и `aiokafka` 0.14.0 — **base**-зависимости. `pika`/`aiopika` в
`src` не импортируются ни разу (0 совпадений), что объясняет падение
`testcontainers.rabbitmq`.

**LOC после миграции: требует измерения** — без бенчмарка любая цифра была бы
выдумкой.

---

## Подтверждено ADOPT (единственные работающие)

**testcontainers** — 13 импортов в 4 файлах, 14 тест-функций, реальный прогон:
```
$ pytest tests/integration/test_testcontainers_smoke.py::TestTestcontainersSmoke::test_postgres_container_starts \
           tests/integration/test_testcontainers_smoke.py::TestTestcontainersSmoke::test_redis_can_ping -q
2 passed, 3 warnings in 19.59s
```
Docker в среде есть (`/usr/bin/docker`, server 29.1.3). В CI запускается фактически:
`.github/workflows/test.yml:47` (`uv sync`, подтягивает dev-группу) → `:51-56`
`uv run pytest tests -n auto` **без `-m`-фильтра**. Custom LOC замены: **0**.

Оговорка: `testcontainers.rabbitmq` не импортируется из-за отсутствующего
`pika` → 2 теста из 8 в smoke-файле скипаются всегда.

**faststream** — base-зависимость, 22 импорта в `src`, все брокеры резолвятся:
```
OK src.backend.infrastructure.clients.messaging.event_bus
OK src.backend.infrastructure.clients.messaging.memory_broker
OK src.backend.infrastructure.sources.mq
OK src.backend.infrastructure.sinks.mq_sink
```
`sources/mq.py:110-130` (`_build_broker`) — единственная точка выбора брокера.
Custom LOC замены: **0** (параллельный bypass в 1566 LOC учтён отдельно как F-AQ12).

---

## Итоговые вердикты

| Библиотека | Вердикт | Доказательство (одна строка) |
|---|---|---|
| openfeature-sdk | **REJECT** | `import openfeature` → 0 совпадений при 117 текстовых упоминаниях; 1265 LOC самописной замещающей реализации |
| schemathesis | **BLOCKED** | runner падает с `No such option: --exitfirst` (exit 2, отчёта нет); CI-job — с `Extra 'dev' is not defined` (uv exit 2) |
| testcontainers | **ADOPT** | `2 passed in 19.59s` на реальных PG+Redis контейнерах |
| faststream | **ADOPT** | base-зависимость, 22 импорта в src, брокеры импортируются в рантайме без ошибок |
| temporalio | **BLOCKED** | `MISSING` в venv и в CI; 37 импортов упираются в `RuntimeError` |
| playwright / patchright | **BLOCKED** | оба `MISSING`; единственный реальный browser-тест исключён `--ignore` в addopts |

## Три дефекта, чинятся тривиально (не чинились — задача read-only)

1. `tools/api_fuzz_runner.py:145` — убрать `--exitfirst`.
2. `.github/workflows/api-fuzz.yml:43` — `uv sync --extra dev` → `uv sync --group dev`.
3. `pyproject.toml:484` — исправить ложное утверждение «temporalio уже в base deps».

Каждый из них сейчас даёт «зелёный» CI при полностью неработающей проверке —
ровно тот случай, который DoD запрещает называть PASS.

## Чего проверить нельзя без прототипа

- Точный LOC-win от openfeature-sdk: пересечение самописного слоя с API SDK не
  проверено (SDK даже не установлен). Оценка 400–700 LOC — гипотеза.
- LOC-win от консолидации NATS/CDC на faststream: прямые клиенты выбраны ради
  пулинга и latency в CDC; без бенчмарка любое число было бы выдумкой.
- Источник установки браузеров в `~/.cache/ms-playwright` при отсутствии
  Python-пакета (признак рассинхрона окружений) — не выяснялся.
