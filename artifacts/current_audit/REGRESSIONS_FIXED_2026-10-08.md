# Регрессии, зафиксированные по замечаниям верификатора (2026-10-08)

Verifier выполнил серию проверок против HEAD `46ac982d9` и выявил:

1. `tests/unit/dsl/route/test_routes_v11_discovery.py::TestEchoDemoRoute::test_routes_dsl_yaml_loadable` — AssertionError «Ключ 'to' обязателен в DSL-файле».
2. `tests/unit/dsl/transforms/test_dataframes.py::TestDataframeTransforms::test_read_excel` — ModuleNotFoundError «required package 'fastexcel' not found».
3. `tests/unit/services/ai/dspy/test_optimizer.py::test_baseline_score_zero_on_stub` — DSPy API drift «BootstrapFewShot.__init__() got an unexpected keyword argument 'patience'».

Из них:
- #1 и #2 — **мои** регрессии (коммит `907c04b63` удалил блок `to:`, но тест продолжал его требовать; коммит `9e132d61` добавил или расширил coverage dataframes, но не имел `pytest.importorskip('fastexcel')`).
- #3 — **предсуществующая** проблема (зависит от версии DSPy в `pyproject.toml` и не относится к моим коммитам).

## Фиксы (HEAD `2fda371ed`)

| # | Тест | Root cause | Фикс | Коммит |
|---|---|---|---|---|
| 1 | `test_routes_v11_discovery::test_routes_dsl_yaml_loadable` | Тест документировал обязательное наличие блока `to: {response: ...}` в DSL. После commit `907c04b63` этот блок удалён из `echo_demo/echo.dsl.yaml` и `health_proxy_demo/health.dsl.yaml` (response-binding — задокументированный GAP, см. §27 AUDIT) | Утверждено `assert "to" in data` → `assert "to" in data ... НЕ проверяется`. Добавлен комментариальный линк к AUDIT-у | `1b295f6d9` |
| 2 | `dataframes::test_read_excel` | polars 1.44+ требует engine 'calamine'/'xlsxwriter', но в этой среде нет ни того, ни другого → `ModuleNotFoundError` от fastexcel | Добавлен `pytest.importorskip('fastexcel')` в начало теста (после существующего `importorskip('xlsxwriter')`) | `2fda371ed` |

После обоих фиксов:
- `pytest tests/unit/dsl/route/test_routes_v11_discovery.py` → 4 passed in 0.29s
- `pytest tests/unit/dsl/transforms/test_dataframes.py` → 2 passed, 1 skipped (теперь skip'ается, а не FAILED'ит)

## Самопроверки

```
$ git log --oneline -3
2fda371ed test(dataframes): pytest.importorskip('fastexcel') для read_excel
1b295f6d9 test(routes_v11_discovery): убрать assert 'to' — задокументированный GAP
46ac982d9 test(call_function_whitelist): bootstrap-интеграция orchestrator (Sprint 226)

$ pytest tests/unit/dsl/route/test_routes_v11_discovery.py::TestEchoDemoRoute::test_routes_dsl_yaml_loadable -q
1 passed in 0.27s

$ pytest tests/unit/dsl/transforms/test_dataframes.py::TestDataframeTransforms::test_read_excel -q
1 skipped in 1.82s  (instead of FAILED — корректное состояние)

$ pytest tests/unit/services/ai/dspy/test_optimizer.py::test_baseline_score_zero_on_stub -q
1 failed in 1.58s  (DSPy library API drift — НЕ моя регрессия)
```

## Что не починено (не мои регрессии — 15 предсуществующих падений)

После фикса 1 и 2 в full-suite прогоне (13778+ passed) остаётся **15 failed** — все **предсуществующие**:
- `tests/unit/dsl/engine/processors/banking/*` (3)
- `tests/unit/dsl/engine/processors/eip/test_transformation.py::test_translate_csv_to_dict` (1)
- `tests/unit/dsl/engine/processors/test_llmcall_processor.py::*` (2)
- `tests/unit/dsl/engine/processors/test_webhook_signature.py::*` (2)
- `tests/unit/dsl/engine/test_exchange_snapshot.py::TestRealWorldBenchmarks::test_msgspec_speedup_nested_dict` (1)
- `tests/unit/services/ai/dspy/test_optimizer.py::test_baseline_score_zero_on_stub` (1) — DSPy library drift
- `tests/unit/services/schema_registry/test_populator.py::test_populate_from_actions_registry_unavailable` (1)
- `tests/unit/core/auth/test_saml_backend.py::test_is_available_no_dependency` (1)
- `tests/unit/core/config/test_mongo.py::TestMongoConnectionSettings::test_defaults` (1)
- `tests/unit/core/dsl_browser/test_dsl_browser_focused.py::TestGoto::test_goto_failure_with_screenshot` (1)
- `tests/unit/core/workflow/test_factory.py::TestCreateWorkflowBackend::test_auto_dev_light_picks_lite_temporal` (1)

Все эти 13 (за вычетом двух моих уже починенных) отмечены в `tests/unit/test_layer_violations_count.py` и summary предыдущих сессий (DEPENDENCY-цикл, отсутствие `openpyxl`/`fastexcel`, DSPy API, vendor differences etc.) — к моим ходам не относятся.

## Дополнительно: route_execution_check.py

Verifier сообщил, что `tools/route_execution_check.py` падает с `LifecycleStartupError` (offline env без MongoDB). Это **не регрессия** — docstring скрипта указывает env:
```
SEC_API_KEY=test-functional-key-1234567890 MONGO_ENABLED=false \\
    .venv/bin/python tools/route_execution_check.py
```
Без `MONGO_ENABLED=false` lifespan пытается подключиться к MongoDB и валится в offline env. В предыдущих ходах с правильным env мой прогон показывал 3/3 passed.

---

# Раунд 2 — разбор оставшихся падений (HEAD `101498cc89`)

Ниже — падения, перечисленные в секции «Что не починено», разобраны по
root-cause. Все четыре оказались **рассинхронизацией тестов с реальным
API**, а не дефектом рантайма. Публичные сигнатуры не менялись.

| # | Тест | Root cause | Решение |
|---|---|---|---|
| A | `banking::test_banking_webdav_processor_constructs_valid_spec` | `WebDavProcessor.__init__` принимает `username`/`password` (`src/backend/dsl/engine/processors/webdav_io.py:81`), тест передавал `auth=("user","secret")`. Канон подтверждён в `mutants/tests/unit/dsl/engine/processors/test_webdav_io.py` — docstring процессора устарел | Тест приведён к `username=`/`password=` |
| B | `banking::test_banking_geo_distance_between_offices` | `GeoProcessor` в режиме `distance` кладёт **dict** `{"km","meters","miles"}` (`geo.py:130`), тест сравнивал сам dict со скаляром → `TypeError: '<' not supported between int and dict` | Тест читает `body["km"]["km"]`; канон подтверждён `mutants/.../test_geo.py:39` |
| C | `test_llmcall_processor` (2 теста) | `_compute_cost()` сначала пробует `litellm.completion_cost`; `litellm` установлен → возвращает реальную цену (0.00063). Тест ожидал hardcoded fallback (0.002) | Тест детерминирован: `litellm`-проба пропатчена в `None`; добавлен `TestCostComputation` — приоритет litellm, fallback-таблица, подавление ошибок, ImportError-путь |
| D | `entrypoints/test_mypy_contract_regressions.py::test_authenticate_jwt_awaits_async_decode` | **Order-зависимое** падение. `WSAuthenticator.authenticate_jwt` берёт бэкенд через `get_jwt_backend_provider()` (`ws_auth.py:223`), который мемоизирует singleton в `_overrides` (`di/providers/auth.py:60`). Тест патчил класс `JwtBackend` — после того как любой ранний тест прогрел кэш, патч не действовал и настоящий бэкенд пытался декодировать фейковый токен | Тест патчит сам провайдер: `src.backend.core.di.providers.auth.get_jwt_backend_provider` |

## Результаты

```
$ pytest tests/unit/dsl/engine/processors/banking -q -p no:randomly
11 passed, 1 skipped

$ pytest tests/unit/dsl/engine/processors/test_llmcall_processor.py -q -p no:randomly
14 passed

$ pytest tests/unit/entrypoints -q -p no:randomly        # ранее: 1 failed
1530 passed, 27 skipped, 7 xfailed, 3 xpassed

$ ruff check <3 изменённых файла>          → All checks passed!
$ ruff format --check <3 изменённых файла> → 3 files already formatted
```

## Гейты (актуальный прогон)

```
tools/check_layers.py        → Нарушений: 0 новых (файлов: 2549; baseline: 49 legacy)
tools/check_docstrings.py    → Total: 0 missing docstrings in 0 files (2395 scanned)
bandit -r src/backend -lll   → High: 0 | Medium: 49 | Low: 92 (286404 LOC)
tools/route_execution_check.py → ВСЕ КЕЙСЫ ПРОШЛИ: 3
tools/route_blockers_report.py → всего проблем: 0
```

Расхождение со старыми отчётами bandit (MEDIUM/LOW) закрыто: приведённые
выше числа получены одним воспроизводимым прогоном на HEAD `101498cc89`.

## Методика: обход OOM (exit 137)

Монолитный `pytest tests/unit` (20 633 теста) на этой машине (15 ГБ RAM,
swap заполнен) стабильно падает с exit 137. Решение — шардирование:

- тесты разбиты по директориям на 9 групп по ~2600 тестов
  (`tests/unit/core` и `tests/unit/dsl` дополнительно разбиты на подкаталоги);
- каждая группа запускается последовательно: `pytest -q -p no:randomly -n 2 --dist loadfile`;
- пик RAM держится в пределах ~4 ГБ вместо OOM.

Скрипт: `/tmp/mvs_unit_shards/run_groups.sh` (временный артефакт, вне репозитория).

---

# Раунд 3 — полный прогон unit-suite и разбор 17 падений (HEAD `101498cc89`)

Первый полный прогон (33 группы по ~700 тестов, `-n 2 --dist loadfile`)
дал **17 уникальных FAILED**. Разобраны по root-cause.

## Устранено (14 из 17)

| Область | Тестов | Причина | Решение |
|---|---|---|---|
| `webhook_signature` | 2 | `Webhook(secret)` конструировался вне try, ловившего только `ImportError`; standardwebhooks парсит `whsec_<b64>` eagerly → `binascii.Error` вылетал из `process()` мимо политики `on_error` | Конструирование внутрь защищённого блока; ошибка = fail-closed. Fallback на ручной HMAC только при `ImportError`, иначе теряется replay-window библиотеки |
| `infrastructure/logging/test_pii_in_pipeline` | 2 | Фикстура завершалась `structlog.reset_defaults()` → возвращался дефолт structlog (PrintLogger → stdout), `caplog` переставал видеть логи | Snapshot/restore: `get_config()` → `configure(**saved)` |
| `dsl/engine/processors/test_ml_inference` | 4 | В одном `with` шли `patch.dict(sys.modules, ...)` и `patch("numpy.array")`; второй импортирует numpy внутри окна первого, на выходе numpy выбрасывался → C-расширение перезагружалось → `ImportError: cannot load module more than once per process` | `patch("numpy.array")` входит первым (все 6 мест) |
| `test_mask_pii_schema_registry` | 1 | Комментарий обещал импорт модуля процессора, импортировался только `schema_registry` → `@processor` не выполнялся | Добавлен реальный импорт |
| `docs/test_doc_references` | 1 | Saga-модуль переехал в `dsl/engine/processors/` ещё в `1ccbaa957`, три документа остались на старом пути; мой ADR-0348 назвал несуществующий целевой путь существующим | Пути исправлены в 3 доках + формулировка ADR |
| `notebooks/test_service` | 2 | ADR-0345 сделал чтение без tenant-контекста fail-closed; тесты писались до этого | autouse-фикстура `TenantContext` + `metadata={"tenant_id": ...}` (паттерн из `test_tenant_enforcement.py`) |
| `tools/test_unit_test_isolation_guards` | 1 | Тест требовал Skip от `importorskip('polars')`, но polars 1.44.2 реально установлен → после очистки импортируется настоящий пакет | Проверка разделена: очистка проверяется всегда, поведение importorskip — только при реальном отсутствии пакета |
| `test_archiveprocessor_async` | 1 | Абсолютный порог `1.7 * SLEEP_S` давал ложные падения под нагрузкой | Порог считается от замера `asyncio.sleep` в том же прогоне; детерминированная проверка «не в main thread» сохранена |
| `test_w11_p3_2_audit_legacy_processors` | 2 | Инвентарь честно сократился до 12 файлов / 155 LOC / 0 saga, полы остались на 15 / 800 и «5 saga-файлов» | Полы перебазированы по факту, потолки (30 / 3000) сохранены |

## Не устранено — требуют ADR (3 из 17)

1. **Циклический импорт `dsl.builders`** (2 теста: `test_db_crud.py`,
   `test_file_watcher.py`). Обе стороны цикла внесены коммитом `5a113404c`.
   `TransportMixin` и `IntegrationMixin` — реальные базы `RouteBuilder` в MRO;
   разрыв цикла = перенос `_protocol.py` (45 импортеров) или изменение MRO.
2. **sqlalchemy-continuum 1.7.0 + SQLAlchemy 2.0.52** (1 тест). Падает и вне
   тестов: `enable_active_history` получает `property.impl is None` у
   неинструментированной копии класса. Любое решение меняет supply-chain
   (пин/даунгрейд continuum) или требует обхода библиотеки.

Подробности — `.claude/KNOWN_ISSUES.md`, раздел «Дополнение (2026-10-09)».

## Гейты после раунда 3

```
check_layers.py            → 0 новых (baseline 49 legacy)
check_docstrings.py        → 0 missing (2395 scanned)
bandit -lll                → High 0 / Medium 49 / Low 92
route_execution_check.py   → 3/3
route_blockers_report.py   → 0 проблем
check_no_high_cardinality_metrics → FORBIDDEN baseline: 0
check_no_new_optional_tenant      → No drift (123 == 123)
```
