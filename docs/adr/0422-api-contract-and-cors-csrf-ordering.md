# ADR-0422 — Контракт клиент↔сервер и порядок CORS/CSRF/auth

* Статус: Accepted (2026-11-02, волна 25, кластер F6b-1)
* Cycle: 183 (волна 25)
* Связан с:
  - ADR-0421 (action-permission enforcement — ролевые 403 в admin-эндпоинтах),
  - ADR-0385 (env-ключи с наследованием — `SEC_CORS_ORIGINS`),
  - ADR-0320/ADR-0365 (allowlist-валидация — тот же принцип для content-type),
  - `docs/adr/0422-api-contract-cors-openapi-and-upload-limits.md` (смежный
    umbrella-ADR кластера F6b: OpenAPI-полнота и лимиты загрузки)
* Затрагивает:
  - `src/frontend/streamlit_app/api_clients/**` (контрактные пути),
  - `src/backend/entrypoints/middlewares/setup_middlewares.py` (порядок),
  - `src/backend/entrypoints/middlewares/cors.py` (новый),
  - `src/backend/entrypoints/middlewares/api_key.py` (bypass OPTIONS),
  - `src/backend/core/config/security.py` (CORS-модель),
  - `tests/unit/frontend/api_clients/test_api_contract_paths.py` (новый),
  - `tests/unit/entrypoints/middlewares/test_cors_preflight.py` (новый),
  - `tests/unit/entrypoints/middlewares/test_csrf_after_auth.py` (новый),
  - `tests/unit/entrypoints/middlewares/test_cors_csrf_order_e2e.py` (новый)

---

## Контекст

Аудит кластера F6b-1 нашёл три дефекта одного класса: **клиент и сервер
разошлись в контракте, а порядок слоёвmiddleware не соответствовал
ожидаемой семантике кодов ошибок**.

1. **Дрейф контракта [high].** Streamlit-клиенты
   (`src/frontend/streamlit_app/api_clients/`) обращаются к API по
   захардкоженным путям, а единственный источник правды о зарегистрированных
   путях — роутер сервера
   (`src/backend/entrypoints/api/v1/routers.py`). Списки разъехались:
   **18 обращений клиента** указывали на незарегистрированные пути и
   получали 404 — `/api/v1/admin/audit/capability` (сервер:
   `/api/v1/audit/capability`), `/api/v1/admin/feature-flags/{name}/toggle`
   (сервер: `/api/v1/admin/feature-flags/toggle` c query-параметрами),
   `/api/v1/orders/*` (канон — `/api/v1/order/*`), `/api/v1/admin/metrics`
   (канон — `/api/v1/admin/system-info`), `/api/v1/admin/trace-logs`
   (канон — `/api/v1/search/logs`), `/api/v1/admin/litellm-gateway/stats`
   (канон — `/api/v1/admin/ai-costs`), `/api/v1/ai/chat` (канон —
   `/api/v1/ai/llm/stream`, SSE), `/api/v1/admin/workflow/step-logs`
   (канон — `/api/v1/admin/workflows` + `/api/v1/admin/workflows/{id}`).
   Ничего не мешало дрейфу вернуться: CI-гейта «клиентские пути ⊆ серверные»
   не существовало.
2. **CORS preflight → 401 [medium].** `OPTIONS /api/v1/invocations` отдавал
   401: `APIKeyMiddleware` (order 110) не пропускал OPTIONS, а
   `CORSMiddleware` стоял на order 30 — при LIFO-семантике `add_middleware`
   (высокий order = внешний) меньший order означает **внутренний** слой,
   то есть CORS выполнялся последним и не мог ответить на preflight.
   Дополнительно `cors_origins` по умолчанию был пустым списком: любой
   origin отклонялся бы с `400 Disallowed CORS origin`.
3. **403 вместо 401 на 253 мутациях [medium].** `CSRFMiddleware` стоял на
   order 740, `AuthRequiredMiddleware` — на 620. Поскольку **высокий order =
   внешний**, CSRF срабатывал РАНЬШЕ auth-guard'а: `POST /api/v1/ai/chat`
   без ключа возвращал `403 csrf_token_missing` вместо `401` — то есть
   клиент не мог отличить «нет credentials» от «не хватает прав».

---

## Решение

### 1. Контракт клиент↔сервер: канон — роутер сервера

* Клиентские пути выровнены с роутером (правки в
  `api_clients/{admin,audit,capability,chat,cached,config,flags,k4,logs,metrics,orders}.py`):
  `/admin/audit/capability` → `/audit/capability`;
  `/admin/feature-flags/{name}/toggle` (тело) →
  `/admin/feature-flags/toggle` (`flag_name`/`enable` в query — ровно так
  их читает `AdminToggleFeatureFlagQuerySchema`);
  `/orders/*` → `/order/*`; `/admin/metrics` → `/admin/system-info`;
  `/admin/trace-logs` → `/search/logs`; `/admin/litellm-gateway/stats` →
  `/admin/ai-costs`; `/admin/workflow/step-logs` → `/admin/workflows`
  (+ `{instance_id}` для drill-down); `/ai/chat` → `/ai/llm/stream`
  (SSE; клиент склеивает `delta` из событий `token`, не-SSE ответ
  возвращается как есть).
* **CI-гейт:** `tests/unit/frontend/api_clients/test_api_contract_paths.py`
  разбирает **AST** клиентов (docstring'и с путями не дают ложных
  срабатываний), собирает все HTTP-пути и требует, чтобы каждый был
  зарегистрирован на сервере (`get_v1_routers()` + legacy-алиасы). Вторая
  проверка запрещает клиенту опираться на скрытые legacy-алиасы
  (`/api/v1/orders/*`, `/api/v1/users/*`, `/api/v1/files/*`).
* Рабочие вызовы не сломаны: query-параметры и тела приведены в соответствие
  с фактическими схемами сервера (`count`/`start_id` у audit-replay,
  `limit` у `/search/logs`, `messages` у `/ai/llm/stream`).

### 2. CORS: preflight без auth и правильный порядок слоёв

* Новый `PreflightCORSMiddleware` (`entrypoints/middlewares/cors.py`) —
  subclass Starlette `CORSMiddleware`: preflight отвечает **204 No Content**
  (вместо `200` + тело `"OK"`) с полным набором `Access-Control-*`;
  запрещённый origin/method по-прежнему даёт информативный `400`.
* CORS поднят на **order 950** — самый внешний built-in: preflight гасится
  сразу и не доходит до auth-слоя; любой ответ (401/403/429/503)
  получает CORS-заголовки и читается браузером.
* `APIKeyMiddleware` пропускает `OPTIONS` (preflight не несёт credentials) —
  так же, как это уже делал `AuthRequiredMiddleware`.
* `SecureSettings.cors_origins` получил **непустой дефолт**
  (`http://localhost:8501`, `http://127.0.0.1:8501`) и остаётся
  настраиваемым через `SEC_CORS_ORIGINS` / `security.cors_origins`
  профиля. Явно пустой список не остаётся «молча»: при старте пишется
  warning `cors.origins_empty` с подсказкой, как задать список.
* В `cors_allow_headers` добавлен **`X-CSRF-Token`**: cookie-based CSRF
  требует этот заголовок, и без него в allowlist браузерный preflight
  мутации получал `400 Disallowed headers` — cross-origin CSRF-флоу был
  невозможен.

### 3. CSRF после аутентификации

* `CSRFMiddleware` перенесён с order 740 на **590** (внутрь
  `auth_required` = 620). По LIFO-семантике меньший order — внутренний
  middleware, то есть CSRF выполняется **после** аутентификации.
* Контракт кодов: нет credentials → **401**; аутентификация прошла,
  CSRF-токена нет → **403 `csrf_token_missing`**. Token-auth
  (`X-API-Key` / `Authorization: Bearer`) остаётся CSRF-exempt.

---

## Альтернативы

1. **Расширить сервер алиасами под старые клиентские пути.** Отклонено:
   канон — роутер сервера; 18 алиасов размножили бы поверхность API и
   оставили два правдивых способа назвать одно и то же.
2. **Генерировать клиентские пути из OpenAPI-схемы.** Отклонено: клиенты —
   лёгкие обёртки над `httpx`; генерация — отдельный проект, а гейт
   «пути ⊆ серверные» решает ту же проблему дешевле.
3. **Оставить CORS внутри auth-слоя и надеяться на bypass OPTIONS.**
   Отклонено: каждая новая auth-middleware снова могла бы гасить preflight;
   CORS снаружи — единственное место, где preflight гарантированно не
   дойдёт до проверки credentials.
4. **Отвечать на preflight статусом 200 (как в Starlette).** Отклонено:
   204 — канонический «preflight без тела»; изменение тривиально и не
   ломает браузеры.
5. **Оставить CSRF снаружи и научить его отличать «нет ключа» от «нет
   CSRF-токена».** Отклонено: CSRF-middleware не должен знать про
   credentials; правильный порядок слоёв дешевле и проверяется тестом.
6. **Проверять порядок только по цифрам реестра.** Отклонено как
   недостаточное: цифры не ловят регрессию в реальном поведении — добавлен
   E2E-тест на настоящей цепочке middleware.

---

## Последствия

* **Позитивные:** UI больше не получает 404 на 18 путях; cross-origin
  клиенты работают (preflight 204 вместо 401); коды ошибок аутентификации
  соответствуют семантике (401 — нет credentials, 403 — не хватает прав);
  дрейф контракта ловится CI-гейтом; cookie-based CSRF работает из
  браузера.
* **Отрицательные / риски:**
  * `cors_origins` по умолчанию указывает на локальный Streamlit — в prod
    оператор обязан задать реальные origins;
  * `chat()` клиента теперь разбирает SSE-поток (не-SSE ответ
    возвращается как есть);
  * `list_step_logs` больше не фильтрует по датам (канонический
    `/admin/workflows` такого фильтра не имеет; диапазон доступен на
    `/admin/workflow-audit/events`).
* **Вне зоны ADR-0422:** удаление legacy-алиасов
  (`entrypoints/api/generator/legacy_aliases.py`), перенос `cors_origins` в
  конфиг-профили прод-окружения, восстановление отдельных ресурсов
  `/admin/metrics` и `/admin/trace-logs`.

---

## Проверка

* `tests/unit/frontend/api_clients/test_api_contract_paths.py` — все
  клиентские пути (AST-разбор) зарегистрированы на сервере; клиент не
  зависит от скрытых legacy-алиасов.
* `tests/unit/entrypoints/middlewares/test_cors_preflight.py` — preflight →
  204 + `Access-Control-*` без ключа и без достижения эндпоинта; чужой
  origin → 400; `APIKeyMiddleware` пропускает OPTIONS; в реальном реестре
  CORS выше api_key/auth_required/csrf; дефолт origins непустой.
* `tests/unit/entrypoints/middlewares/test_csrf_after_auth.py` — цепочка
  собирается из **реального реестра**: без ключа → 401; аутентификация
  прошла, CSRF-токена нет → 403 `csrf_token_missing`; в реестре
  `csrf < auth_required`.
* `tests/unit/entrypoints/middlewares/test_cors_csrf_order_e2e.py` — **реальная
  цепочка** middleware (реальные настройки и реестр): OPTIONS без ключа →
  204 + `Access-Control-Allow-Origin`; preflight с `X-CSRF-Token` разрешён;
  эндпоинт не достигается; POST без ключа → 401 без `csrf_token_missing`;
  401 читается из браузера (CORS-заголовки есть); POST с валидным
  API-ключом доходит до эндпоинта (CSRF не мешает token-auth).
  Тест импортирует все модули пакета `middlewares` на этапе collection:
  middleware делает `from ...config.settings import settings` на уровне
  модуля, поэтому модуль, впервые импортированный под подменой настроек
  (внутри другого теста), навсегда получает `MagicMock` вместо `Settings` —
  order-dependent pollution (ADR-0404). Импорт на collection фиксирует
  реальные настройки и убирает зависимость от порядка запуска файлов.
* Гейты: `ruff check` по изменённым файлам — чисто;
  `tools/config_audit.py --scope orphans` → 0;
  `tools/check_layers.py --strict` → 41 (baseline не изменился);
  `tools/checks/mypy_budget.py` → OK.

---

## Открытое (owner-задачи)

1. **Прод-origins CORS.** Владелец: эксплуатация/безопасность. Критерии:
   в `config_profiles/prod.yml` задан явный `security.cors_origins`
   (без `*`), в логах старта нет `cors.origins_empty`.
2. **Удаление legacy-алиасов.** Владелец: платформа/frontend. Критерии:
   после удаления `legacy_aliases.py` гейт
   `test_api_contract_paths.py` зелёный, ни одна страница Streamlit не
   обращается к `/api/v1/{orders,users,files}/*`.
3. **Индекс ADR.** `docs/adr/INDEX.md` не редактировался (правило
   кластера) — индекс перегенерируется отдельной операцией
   (`tools/build_adr_index.py`).

---

## Связи

* ADR-0421 — ролевые 403 в admin-эндпоинтах (`require_admin`).
* ADR-0385 — env-ключи с наследованием (`SEC_CORS_ORIGINS`).
* ADR-0412 — endpoint-контракты sidecar'ов.
* `src/backend/entrypoints/api/v1/routers.py` — канонический реестр путей v1.
* `src/backend/entrypoints/middlewares/registry.py` — LIFO-семантика
  `order` (высокий order = внешний middleware).
* `src/backend/entrypoints/middlewares/auth_required.py` —
  `DEFAULT_PUBLIC_PATH_PREFIXES` (источник «public» для auth-guard'а).
* `src/backend/core/errors.py` — `build_error_envelope` (формат 4xx-ответов).
