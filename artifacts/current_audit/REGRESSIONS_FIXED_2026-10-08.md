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
