# Tutorial 03 — RouteLoader hot-reload

> **Prerequisites:** Прочитан `01_first_route.md`. Feature-flag
> `route_loader_hot_reload` = True. ~30 минут.

## Цель

Научиться менять YAML-описания route в `routes/<name>/` без рестарта
приложения. Изменения в `route.toml` или `*.dsl.yaml` подхватываются
hot-reloader'ом в течение 3 секунд.

## Шаги

### 1. Создать тестовый route

```bash
mkdir -p routes/hello
cat > routes/hello/route.toml <<EOF
name = "hello"
version = "0.1.0"
requires_core = "^1.0"
[capabilities]
EOF

cat > routes/hello/hello.dsl.yaml <<EOF
from:
  http:
    method: GET
    path: /api/v1/hello
steps:
  - response:
      code: 200
      body: {message: "Hello, World!"}
EOF
```

### 2. Запустить app + проверить route

```bash
curl http://localhost:8000/api/v1/hello
# {"message": "Hello, World!"}
```

### 3. Изменить YAML — наблюдаем reload

Откройте `routes/hello/hello.dsl.yaml`, измените `message` на
`"Hello, Hot-Reload!"`. Сохраните.

В логах приложения:

```
hot_reloader.route_reloaded route_name=hello
```

### 4. Проверить новое поведение (без рестарта)

```bash
curl http://localhost:8000/api/v1/hello
# {"message": "Hello, Hot-Reload!"}
```

### 5. Удалить route — unload

```bash
rm -rf routes/hello
# logs: hot_reloader.route_unloaded route_name=hello
curl http://localhost:8000/api/v1/hello
# 404 Not Found
```

## What's next?

* Tutorial 04 — Temporal workflow с XOR/AND gateways.
* Runbook `routes-feature-flag-rollout.md` — production rollout
  hot-reload (feature_flag default-OFF до staging валидации).
* ADR-0056 — V11 routes контракт (`requires_core`, `capabilities`,
  `feature_flag`).
