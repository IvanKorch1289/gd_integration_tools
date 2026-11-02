# ADR-0423 — Полнота OpenAPI-схемы и лимиты загрузки файлов (кластер F6b-2)

* Статус: Accepted (2026-11-02, волна 25, кластер F6b-2 — полнота OpenAPI + лимиты загрузки)
* Cycle: 184 (волна 25)
* Связан с:
  - ADR-0422 (контракт API, CORS/CSRF, полнота OpenAPI и лимиты загрузки — волна 24, предшественник),
  - ADR-0421 (action-permission enforcement — ролевые 403),
  - ADR-0385 (env-ключи с наследованием),
  - ADR-0112/ADR-0365 (allowlist-валидация — тот же принцип для content-type)
* Затрагивает:
  - `src/backend/entrypoints/api/openapi_completeness.py` (новый),
  - `src/backend/entrypoints/api/openapi_security.py`,
  - `src/backend/entrypoints/api/v1/endpoints/files.py`,
  - `tests/unit/entrypoints/api/test_openapi_completeness.py` (новый),
  - `tests/unit/entrypoints/api/v1/test_files_upload_stream_content_type.py` (новый)

---

## Контекст

Волна 24 (ADR-0422) закрыла две половины аудита кластера F6b:
4xx-ответы для защищённых операций и лимиты загрузки файлов
(`await file.read()` → чтение чанками, 413/415). Кластер F6b-2 (эта волна)
закрывает остаток — **неполноту самой спецификации**.

Измерение «сырой» схемы приложения (без аннотаций OpenAPI, 446 операций):

| Метрика | Значение |
|---|---|
| операций без единого 4xx-ответа | **206** |
| мутаций без `requestBody` | **188** |
| живых маршрутов, скрытых от схемы (`include_in_schema=False`) | **16** |
| операций, отдающих 4xx, не описанных в схеме | 413/415 (загрузка), 401/429 (step-up) |

Причины по пунктам:

1. **`requestBody` (188 мутаций).** FastAPI выводит `requestBody` только для
   параметров тела, объявленных в сигнатуре обработчика. Обработчики,
   читающие тело вручную (`await request.json()` — auto-registered actions и
   legacy-алиасы, `request.stream()` — streaming-загрузка, `await
   request.form()` — SAML ACS, `await request.body()` — SOAP/webhooks),
   тела в схеме не имеют, хотя принимают его в рантайме. Клиент,
   сгенерированный из спецификации, не знает, что посылать.
2. **16 legacy-алиасов** (`/api/v1/orders/*`, `/api/v1/users/*`,
   `/api/v1/files/*`, `/api/v1/orderkinds/*`) зарегистрированы с
   `include_in_schema=False`: маршруты живые, но спецификация о них молчала,
   а Streamlit на них опирается (`api_clients/orders.py` и др.).
3. **4xx, о которых схема молчала.** Буферизованная загрузка отдаёт 413
   (лимит размера) и 415 (content-type вне allowlist'а), step-up/login —
   401 (нет `X-Step-Up-Token`) и 429 (rate-limit per IP). В схеме их не
   было, хотя `annotate_error_responses` закрывал только 401/403.
4. **Path-параметры вне схемы.** Часть action-роутов объявляет placeholder
   в пути (`/storage/scan_file/{file_uuid}`), но не биндит его в сигнатуре:
   FastAPI такой параметр в `parameters` не выводит, хотя маршрут без
   сегмента не совпадёт. Клиент по спецификации не знает, что сегмент
   обязателен.

---

## Решение

### 1. Новый слой полноты — `entrypoints/api/openapi_completeness.py`

Слой **не выдумывает контракт**: `requestBody` добавляется только там, где
обработчик действительно читает тело, а каждое исключение получает причину.

* `annotate_request_bodies(schema)` — `requestBody` для мутаций, читающих
  тело вручную. Правила (по путям, а не по точным URL: монтирование
  GraphQL/SOAP/webhook-роутов зависит от конфигурации приложения):

  | Правило | Media-type | Кто читает тело |
  |---|---|---|
  | префикс `/api/v1/auto/` | `application/json` | `auto_register.py` (`request.json()`) |
  | суффикс `/storage/upload-stream` | `application/octet-stream` | `files.py` (`request.stream()`) |
  | суффикс `/saml/acs` | `application/x-www-form-urlencoded` | `auth_saml.py` (`request.form()`) |
  | суффикс `/graphql` | `application/json` | GraphQL-роутер (тело запроса) |
  | префикс `/soap` | `application/xml` | `soap_handler.py` (`request.body()`) |
  | префикс `/express/` | `application/json` | `express/router.py` (`request.json()`) |
  | префикс `/webhooks/` | `application/json` | `webhook/handler.py` (`request.body()`) |

  Тело помечается `required: false` — обработчики принимают и пустое тело.
* `annotate_legacy_aliases(app, schema)` — скрытые legacy-маршруты
  публикуются как операции с `deprecated: true` и `x-legacy-alias: true`
  (+ `requestBody` для POST/PUT — алиас читает JSON вручную). Инфраструктурные
  алиасы (`/healthz`, `/livez`, `/metrics`) в схему не попадают: они не API.
* `annotate_path_parameters(schema)` — path-параметры, объявленные в
  шаблоне пути, но не выведенные FastAPI, описываются как обязательные
  (`in: path`, `required: true`).
* `annotate_operation_errors(schema)` — реальные 4xx не-auth слоя: 413/415
  для загрузки, 401/429 для `login`/`step-up-request`.
* `classify_missing_request_body()` + `undocumented_mutations_without_request_body()` —
  **таксономия причин и гейт**: у каждой мутации без `requestBody` должна
  быть причина; недокументированных быть не должно.

### 2. Таксономия исключений (все 69 актуальных)

| Причина | Операций |
|---|---|
| идентификатор в пути — тело контрактом не предусмотрено | 48 |
| параметры в query — тело контрактом не предусмотрено | 10 |
| auto-registered action: payload в query (метод без тела) | 6 |
| legacy-контракт action'а: ключ в query | 1 |
| операция без параметров (сброс кэша / перезагрузка конфигурации / перезагрузка IP-правил) | 3 |
| выдача step-up-токена по IP-контексту | 1 |

### 3. Подключение

`openapi_security.apply_security_to_openapi()` вызывает
`annotate_completeness(app, schema)` перед `annotate_error_responses(schema)`
(порядок: security → legacy-алиасы → path-параметры → `requestBody` →
4xx → 401/403 для защищённых операций). Отдельный файл app-factory не
трогался: точка подключения — уже существующая обёртка `app.openapi`.

### 4. Загрузка файлов

* `HTTP_413_REQUEST_ENTITY_TOO_LARGE` → `HTTP_413_CONTENT_TOO_LARGE`:
  прежнее имя объявлено deprecated в Starlette и печатало warning.
* Streaming-эндпоинт `/storage/upload-stream` проверяет `content-type` по
  тому же allowlist'у, что и буферизованная загрузка → **415 до чтения
  тела** (загрузка в S3 шла мимо allowlist'а). Content-type не передан —
  запрос принимается (прежний контракт не меняется).
* Лимиты (`MAX_UPLOAD_BYTES` = 64 MiB, `MAX_STREAM_UPLOAD_BYTES` = 1 GiB)
  остались константами модуля; вынос в конфиг-модель — вне зоны
  (см. «Открытое»).

### 5. Итог

| Метрика | «сырая» схема | после аннотаций |
|---|---|---|
| операций | 446 | 462 (+16 legacy-алиасов) |
| операций без 4xx | 206 | **3** (все public и не мутации: `/health`, `/ready`, `/api/v1/auth/methods`) |
| мутаций без `requestBody` | 188 | **69**, у всех документированная причина |
| недокументированных исключений | — | **0** |
| мутаций без `requestBody` и без причины (гейт) | — | 0 (иначе падает тест) |

---

## Альтернативы

1. **Дописать `requestBody` всем 188 мутациям.** Отклонено: это была бы ложь
   в спецификации (`DELETE /order/delete/{id}` тела по контракту не имеет);
   документированное исключение с причиной честнее.
2. **Перенести тело в сигнатуры обработчиков** (`Body(...)` в
   `auto_register.py` / `legacy_aliases.py`). Отклонено: меняется рантайм-
   контракт (невалидное тело перестаёт быть допустимым, 422 вместо
   терпимого разбора) и затрагиваются файлы вне зоны кластера.
3. **Оставить legacy-алиасы скрытыми.** Отклонено: схема молчала о живом
   маршруте, на котором стоит UI; «не молча» — публикуем как `deprecated`.
4. **Удалить legacy-алиасы.** Отклонено: клиентStreamlit
   (`45_Админ.py` → `/api/v1/users/all`) ещё зависит от них; удаление —
   отдельная owner-задача с миграцией клиента.
5. **Лимиты загрузки — в конфиг-модель (`core/config`).** Отклонено для этой
   волны: `core/config/**` вне зоны кластера; константы допустимы по
   требованию аудита («настройка или константа»).
6. **Не проверять content-type в streaming-загрузке.** Отклонено: эндпоинт
   писал в S3 любой тип (включая HTML/исполняемые файлы), обходя allowlist
   буферизованной загрузки; проверка выполняется до чтения тела.
7. **Проверять content-type в streaming-загрузке строго (обязателен).**
   Отклонено: ломает действующий контракт (content-type опционален).

---

## Последствия

* **Позитивные:** опубликованная спецификация описывает реальные ответы
  (4xx) и реальные тела (196 операций с `requestBody`); клиент-генератор
  получает корректные запросы к 120 auto-action'ам, SOAP, webhooks и
  streaming-загрузке; скрытые legacy-маршруты видны и помечены
  `deprecated`; обязательные path-сегменты описаны; новые мутации без тела
  не могут появиться молча — гейт падает.
* **Отрицательные / риски:**
  * правила сопоставления путей (префикс/суффикс) требуют ревизии при
    новых монтированиях; гейт на это отреагирует падением — это намеренно;
  * публикация legacy-алиасов в схеме показывает их клиент-генераторам —
    они помечены `deprecated`, но формально «живой» контракт;
  * allowlist content-type в streaming-загрузке может отклонить ранее
    принимаемые типы (список расширяется одной правкой константы);
  * `annotate_path_parameters` описывает параметр, который рантайм не
    биндит в обработчик (см. «Открытое», п. 2) — это правда о маршрутизации,
    но не о бизнес-логике.
* **Вне зоны ADR-0423:** удаление legacy-алиасов; перенос лимитов загрузки и
  allowlist в конфиг-профили; исправление небиндинга path-параметров в
  storage-action'ах; чистка Streamlit-зависимости от `/api/v1/users/all`.

---

## Проверка

* `tests/unit/entrypoints/api/test_openapi_completeness.py` —
  `requestBody` есть у мутаций, читающих тело (auto-action, streaming —
  бинарное тело); ни одной мутации без тела без документированной причины
  (гейт по живой схеме приложения); у каждой мутации есть 4xx; 413/415 у
  загрузки, 401/429 у login/step-up; legacy-алиасы опубликованы как
  `deprecated` и несут `requestBody`; инфраструктурные алиасы не публикуются;
  префикс auto совпадает с регистратором; аннотация идемпотентна.
* `tests/unit/entrypoints/api/v1/test_files_upload_stream_content_type.py` —
  недопустимый content-type → 415 **без чтения тела**; разрешённый —
  прежний контракт ответа; отсутствие content-type — прежний контракт.
* `tests/unit/entrypoints/api/v1/test_files_upload_limits.py` (ADR-0422) —
  зелёный: 413/415, файл не читается целиком в RAM, streaming > лимита → 413.
* Гейты: `ruff check` по изменённым файлам — чисто;
  `tools/config_audit.py --scope orphans` → 0;
  `tools/check_layers.py --strict` → 41 (baseline не изменился);
  `tools/checks/mypy_budget.py` → OK;
  `tools/check_docstrings.py` → 0 missing.
* Регресс-прогон: `tests/unit/entrypoints` → 1732 passed.

---

## Открытое (owner-задачи)

1. **Удаление legacy-алиасов.** Владелец: платформа/frontend. Критерии:
   после удаления `legacy_aliases.py` гейт `test_api_contract_paths.py`
   зелёный, ни одна страница Streamlit не обращается к
   `/api/v1/{orders,users,files,orderkinds}/*` (сейчас — `45_Админ.py`).
2. **Небиндинг path-параметров storage-action'ов.** Владелец: платформа.
   `/storage/{download_file,get_download_link_file,get_file_base64,scan_file}/{file_uuid}`
   объявляют placeholder, но `ActionSpec.path_model` не задан, поэтому ключ
   не доходит до сервиса. Схема теперь описывает сегмент как обязательный
   (маршрутизация честна), но бизнес-часть — вне зоны ADR-0423.
3. **Лимиты загрузки и allowlist в конфиг.** Владелец: платформа. Критерии:
   значения вынесены из констант `files.py` в модель настроек и
   переопределяются per-деплой.
4. **Индекс ADR.** `docs/adr/INDEX.md` не редактировался (правило кластера) —
   индекс перегенерируется отдельной операцией.

---

## Связи

* ADR-0422 — предыдущая волна: 4xx через `annotate_error_responses`,
  лимиты загрузки (`_read_limited`, `_limited_stream`).
* ADR-0421 — ролевые 403 в admin-эндпоинтах.
* ADR-0385 — env-ключи с наследованием (`SEC_CORS_ORIGINS`).
* `src/backend/entrypoints/api/openapi_security.py` — аннотация `security` и
  401/403; точка подключения полноты.
* `src/backend/entrypoints/api/openapi_completeness.py` — новый слой полноты.
* `src/backend/entrypoints/api/v1/endpoints/files.py` — лимиты и allowlist
  загрузки.
* `src/backend/entrypoints/api/generator/auto_register.py` — auto-действия
  (`_AUTO_PREFIX`), чьё тело читается вручную.
* `src/backend/entrypoints/middlewares/login_step_up.py` — 401/429 вне
  auth-guard'а.
* `src/backend/entrypoints/middlewares/auth_required.py` —
  `DEFAULT_PUBLIC_PATH_PREFIXES` (источник признака «public»).
