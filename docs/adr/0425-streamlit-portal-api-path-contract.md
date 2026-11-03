# ADR-0425 — Контракт API-путей портала: гейт по `pages/` + честные панели

* Статус: Accepted (2026-11-03, волна 26)
* Cycle: 186 (волна 26)
* Связан с:
  - ADR-0422 (контракт клиент↔сервер, CORS/CSRF-порядок),
  - ADR-0423 (полнота OpenAPI, загрузка файлов),
  - ADR-0100 (прецедент: мёртвый/вводящий в заблуждение код либо удаляется,
    либо чинится),
  - ADR-0284 (матрица межслойных импортов — новых нарушений не добавляем)
* Затрагивает:
  - `tests/unit/frontend/api_clients/test_api_contract_paths.py` (гейт теперь
    сканирует и `src/frontend/streamlit_app/pages/**`),
  - 18 страниц портала (`src/frontend/streamlit_app/pages/**`),
  - `src/frontend/streamlit_app/pages/_groups/cron/builder/render.py`

---

## Контекст

ADR-0422 ввёл CI-гейт «каждый путь клиента существует на сервере», но сканировал
только каталог `src/frontend/streamlit_app/api_clients`. Streamlit-страницы
(`src/frontend/streamlit_app/pages/**`, 36+ страниц) обращаются к API
**напрямую** — `client._request("GET", "/api/v1/…")`, `client.get("…")` — минуя
слой клиентов, и потому были вне зоны гейта.

Аудит страниц (AST-скан, тот же алгоритм, что и в гейте) показал **39
запросов, которых сервер не регистрирует** — то есть 39 панелей портала,
которые всегда отдавали 404, а страница глотала исключение и показывала
«Не удалось получить …» либо пустую таблицу. Классификация:

| Класс | Примеры | Решение |
|---|---|---|
| **Потерян префикс `/api/v1`** | `/hitl/pending`, `/tech/degradation/snapshot`, `/admin/model-registry/models` (base_url клиента = `http://host:8000`, без `/api/v1`) | путь → канонический |
| **Переименование/другой ресурс** | `/api/v1/routes` → `/api/v1/routes/inventory`; `/api/v1/admin/audit` → `/api/v1/audit/capability`; `/api/v1/users/all` → `/api/v1/user/all/`; `/api/v1/admin/templates` → workflow-templates | путь → живой канон |
| **Legacy-алиас** | `/api/v1/users/all` (deprecated-алиас `users.get`, вне OpenAPI) | путь → канонический CRUD |
| **Эндпоинта нет и capability нет** | `/api/v1/admin/processes/active`, `/api/v1/admin/queues/summary`, `/api/v1/admin/prompt-versions/{n}/compare`, `/api/v1/admin/sql/query` | панель явно сообщает «серверный endpoint не реализован» |
| **Эндпоинта нет, capability есть, но не подключена** | guardrails-метрики (`GuardrailsMetricsService` не в DI), prompt-versions (`PromptRegistry` без list/activate), webhook scheduler (`WebhookScheduler` не создан), storage list | панель явно сообщает; реализация — в owner-задачах |

Особый случай — `tests/unit/core/test_no_audit_proxy.py`: тест делал bare
`sys.modules.pop("src.backend.core.audit")` / `…facade` без восстановления.
После `pop` любой последующий импорт пересоздавал объект пакета, а
кэшированный подмодуль `facade.audit_service` не переустанавливал атрибут на
родителе — из-за этого чужие тесты, патчащие
`src.backend.core.audit.facade.audit_service.*` по dotted-пути, падали в setup
с `AttributeError` (ADR-0404/0410: order-dependent падения не банкуются, а
устраняются).

---

## Решение

1. **Гейт расширен на страницы.** `test_api_contract_paths.py` сканирует AST
   каталогов `api_clients/` **и** `pages/`; правила те же:
   * путь, который страница запрашивает, обязан регистрироваться сервером;
   * зависимость от скрытых legacy-алиасов (`/api/v1/users/*`,
     `/api/v1/orders/*`, `/api/v1/files/*`) запрещена;
   * путь-шаблон, собираемый из префикса и переменной (`f"/api/v1{path}"`),
     статически нерезолвится и проверке не подлежит.
2. **Пути приведены к канону** (22 вызова): префикс `/api/v1`, канонические
   ресурсы (`/api/v1/routes/inventory`, `/api/v1/audit/capability`,
   `/api/v1/user/all/`, `/api/v1/admin/cron/list`,
   `/api/v1/admin/workflow-audit/events`, `/api/v1/admin/resilience-profiles`).
3. **Панели без серверного endpoint'а больше не делают запрос** — вместо
   swallowed 404 страница показывает явное сообщение о том, что endpoint не
   реализован (ADR-0100: мёртвый код не маскируется под работающий).
4. **Новые серверные endpoint'ы в этой волне не создавались.** Для каждого
   отсутствующего endpoint'а проверена capability в бэкенде: там, где её нет
   (`processes/active`, `queues/summary` для Kafka/RabbitMQ, prompt-compare),
   реализация была бы спекулятивной фичей; там, где сервис есть, но не
   подключён к DI (guardrails-метрики, `WebhookScheduler`), подключение и
   HTTP-обёртка вынесены в owner-задачи.
5. **`tests/unit/core/test_no_audit_proxy.py` больше не чистит `sys.modules`**
   (proxy удалён из исходников — кэш чистить не требуется), а
   `tests/unit/dsl/test_action_registry_permissions.py` патчит объект модуля
   вместо dotted-пути (устойчиво к любому пересозданию пакета).

---

## Последствия

* **Позитив:** 39 панелей портала перестали быть «мёртвыми» — часть из них
  (HITL, degradation snapshot, RAG strategy-stats, scheduler/dlq, cron-list,
  model-registry, feedback, audit, routes inventory, resilience profiles,
  workflow-audit events) теперь реально работает; остальные честно объясняют
  отсутствие backend'а. Регрессия «страница зовёт несуществующий путь»
  закрыта гейтом.
* **Известные ограничения:**
  * фильтры audit-журнала (период/маршрут/пользователь/статус) применяются
    локально: `GET /api/v1/audit/capability` отдаёт последние N записей без
    серверных фильтров;
  * панели процессов/очередей/prompt-lab не восстановят данные до появления
    соответствующих endpoint'ов (owner-задачи).
* **Owner-задачи (реализация capability):**
  1. `GuardrailsMetricsService` → DI + `GET /api/v1/admin/guardrails-metrics`,
     `POST …/{tenant_id}/false-positive`;
  2. `PromptRegistry` → list/activate/compare + `GET /api/v1/admin/prompt-versions*`;
  3. `WebhookScheduler` → DI + `GET /api/v1/webhooks/scheduled`,
     `POST /api/v1/webhook/schedule` (с SSRF-валидацией);
  4. `GET /api/v1/storage/list|get|download` (по ключу) — сейчас есть только
     операции по `file_uuid`;
  5. `GET /api/v1/admin/pools/snapshot` (pool-менеджер умеет `get_metrics`);
  6. `GET /api/v1/admin/processes/active`, `GET /api/v1/admin/queues/summary`;
  7. `POST /api/v1/admin/sql/query` — только read-only SELECT с валидацией и
     аудитом (в текущей волне сознательно не поднимался).
