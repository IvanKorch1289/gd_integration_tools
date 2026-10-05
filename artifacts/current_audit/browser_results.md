# BROWSER: результаты прогона Playwright

- HEAD: `2d9f4323ba7398c3de67f0a3cea044c557b2eb6f`
- Базовый адрес: `http://127.0.0.1:8137` — только loopback, выхода в интернет нет
- Браузер: Chromium, явный `executable_path` = `/home/user/.cache/ms-playwright/chromium-1243/chrome-linux64/chrome`
- Расхождение версий: библиотека Playwright ожидает другую сборку Chromium, поэтому браузер подключён по явному пути, без скачивания

**Итог: 6 PASS, 0 FAIL, 0 SKIPPED.**

> `SKIPPED` и `ENV_BLOCKED` **не считаются PASS**.

| Проверка | Страница | HTTP | Ожидаем | Вердикт |
|---|---|---:|---:|---|
| `swagger-ui` | Swagger UI | 200 | 200 | **PASS** |
| `redoc` | ReDoc | 200 | 200 | **PASS** |
| `openapi-json` | OpenAPI 3.1 (JSON) | 200 | 200 | **PASS** |
| `graphql-unauth` | GraphQL без auth | 401 | 401 | **PASS** |
| `graphql-auth` | GraphQL с auth | 200 | 200 | **PASS** |
| `auth-header-masking` | Маскирование чувствительных заголовков | 401 |  | **PASS** |

## Диагностика

### swagger-ui
- URL: `http://127.0.0.1:8137/docs`
- console errors: нет
- page errors: нет
- неуспешные запросы: нет
- скриншот: `browser_artifacts/swagger-ui.png`

### redoc
- URL: `http://127.0.0.1:8137/redoc`
- console errors: нет
- page errors: нет
- неуспешные запросы: нет
- скриншот: `browser_artifacts/redoc.png`

### openapi-json
- URL: `http://127.0.0.1:8137/openapi.json`
- console errors: ['error: Failed to load resource: the server responded with a status of 401 (Unauthorized)']
- page errors: нет
- неуспешные запросы: нет
- скриншот: `browser_artifacts/openapi-json.png`

### graphql-unauth
- URL: `http://127.0.0.1:8137/api/v1/graphql`
- console errors: ['error: Failed to load resource: the server responded with a status of 401 (Unauthorized)', 'error: Failed to load resource: the server responded with a status of 401 (Unauthorized)']
- page errors: нет
- неуспешные запросы (1):
  - `{"url": "http://127.0.0.1:8137/api/v1/graphql", "status": 401}`
- скриншот: `browser_artifacts/graphql-unauth.png`

### graphql-auth
- URL: `http://127.0.0.1:8137/api/v1/graphql`
- console errors: нет
- page errors: нет
- неуспешные запросы: нет
- скриншот: `browser_artifacts/graphql-auth.png`

### auth-header-masking
- URL: `http://127.0.0.1:8137/api/v1/actions/inventory`
- console errors: нет
- page errors: нет
- неуспешные запросы: нет
- заголовки ответа (замаскированы):
  - `date: Mon, 05 Oct 2026 07:03:43 GMT`
  - `server: uvicorn`
  - `content-type: application/json`
  - `www-authenticate: Bearer`
  - `content-length: 36`
  - `set-cookie: <masked>`
  - `traceparent: 00-d04904bdcdaacd63e703663e7b5da30e-bc9f52c1617ea5d3-03`
  - `strict-transport-security: max-age=63072000; includeSubDomains`

## Сохранённые артефакты

- `browser_artifacts/trace.zip` — Playwright trace (screenshots, snapshots, sources)
- `browser_artifacts/*.png` — скриншоты страниц

## Что осталось непроверенным (честно)

- **Streamlit-портал — `NOT_RUN`**: отдельное приложение (`src/frontend/streamlit_app`) в этом прогоне не поднималось.
- **RPA local test page — `ENV_BLOCKED`**: RPA-пул в приложение не подключён (F-AP6), навигация недостижима; проверялось лишь отсутствие внешних обращений.
- **login flow — `NOT_RUN`**: требует интерактивного ввода учётных данных и работающего хранилища пользователей.

Секреты и PII в артефакты не попадают: значения заголовков авторизации маскируются, тексты исключений Playwright не записываются.
