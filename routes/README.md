# routes/ — DSL-routes как «лёгкие плагины» (V11.1a)

## Зачем эта директория

`routes/<name>/` содержит декларативные маршруты интеграционной шины. Каждый route — это
независимый «лёгкий плагин»: он описывает источник (endpoint), шаги обработки и назначение,
без необходимости писать Python-код. Основан на ADR-0056 (Routes V11.1a).

Ключевые свойства:
- **Capability-gate**: каждый route декларирует используемые capabilities через `route.toml`; доступ
  вне декларации → `CapabilityDeniedError`.
- **Feature-flag**: каждый route можно включить/выключить через `route.toml::[route.feature_flag]`.
- **Hot-reload**: RouteLoader отслеживает изменения `route.toml` без перезапуска приложения.
- **SLO-aware**: `[route.slo]` задаёт целевые p95/p99 задержки и RPS для мониторинга.
- **Semver-совместимость**: `requires_core` задаёт минимальную и максимальную версию ядра.

## Структура route

```
routes/<name>/
  route.toml       # manifest: capabilities, slo, schedule, feature_flag, requires_core
  *.dsl.yaml       # DSL steps[]: proxy, transform, audit, validate_request, call_function, ...
```

## Как добавить новый route

1. Создай директорию `routes/<my_route>/`.
2. Создай `route.toml` по образцу `health_proxy_demo/route.toml`:
   - укажи `capabilities[]` — только те ресурсы, которые route действительно использует;
   - задай `[route.slo]` с реалистичными значениями;
   - добавь `[route.feature_flag]` с именем соответствующего feature-flag (default-OFF).
3. Создай `my_route.dsl.yaml` с полем `from:`, списком `steps:` и полем `to:`.
4. Убедись, что feature-flag зарегистрирован в `src/backend/core/config/features.py`.
5. Запусти smoke-тест: `python -c "import tomllib; tomllib.load(open('routes/<my_route>/route.toml', 'rb'))"`.

## Reference routes (образцы)

| Route | Назначение | Steps |
|---|---|---|
| `health_proxy_demo` | Прокси GET /api/v1/demo/health → localhost:9000 | proxy + audit |
| `echo_demo` | POST /api/v1/demo/echo с валидацией и трансформацией | validate_request + transform |

## Ссылки

- **ADR-0056**: `docs/adr/ADR-0056-routes-v11-1a-dsl-routes-lightweight-plugins.md`
- **RouteLoader**: `src/dsl/route/loader.py`
- **Feature flags**: `src/backend/core/config/features.py`
- **PLAN.md V15**: раздел R-V15-2 (Routes как «лёгкие плагины»)
