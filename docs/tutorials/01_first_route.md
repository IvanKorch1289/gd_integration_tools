# Создание первого DSL-маршрута

В этом руководстве вы создадите минимальный HTTP-роут через декларативный DSL
и убедитесь, что он зарегистрирован в системе.

## Что нам потребуется

- Python 3.14+, установленный `uv`
- Запущенное dev-окружение (`make dev-light`)
- Базовое понимание YAML

## Шаг 1: Создайте директорию маршрута

DSL-маршруты живут в `routes/<name>/` согласно R-V15-2 (Routes как лёгкие плагины).

```bash
mkdir -p routes/hello_world
```

## Шаг 2: Добавьте манифест `route.toml`

```toml
# routes/hello_world/route.toml
name = "hello_world"
version = "0.1.0"
requires_core = ">=15.0.0"
tenant_aware = false

[slo]
max_latency_p95_ms = 200
```

## Шаг 3: Добавьте шаги в `hello.dsl.yaml`

```yaml
# routes/hello_world/hello.dsl.yaml
from:
  http:
    method: GET
    path: /api/v1/hello

steps:
  - call_function:
      ref: src.backend.services.core.hello:greet

to:
  response:
    code: 200
    body:
      message: ${body.greeting}
```

## Шаг 4: Проверьте регистрацию

```bash
make routes
```

В выводе появится строка с `hello_world`. Это подтверждает, что RouteLoader
обнаружил ваш маршрут.

## Итог

Вы создали DSL-маршрут в 3 шага: манифест → шаги → проверка.
Следующий шаг — добавление процессора (см. `howto/01_add_processor.md`).
