# Волна 26 (2026-11-03) — аудит портала, auth-поверхностей и tenant-фильтра

Продолжение вехи «воркфлоу / DSL / отказоустойчивость / удобство / документация».
Волна закрывает 3 класса дефектов, найденных аудитом и полным прогоном
`tests/unit`.

---

## 1. Контракт API-путей портала (ADR-0425)

**Дефект.** Гейт контракта клиент↔сервер (ADR-0422) сканировал только
`src/frontend/streamlit_app/api_clients`. Страницы портала (`pages/**`, 36+)
х��дят в API напрямую (`client._request("GET", "/api/v1/…")`) и были вне
гейта. AST-скан страниц нашёл **39 запросов, которых сервер не регистрирует** —
панели, которые всегда давали 404, а страница глотала исключение.

| Класс | Примеры | Что сделано |
|---|---|---|
| потерян префикс `/api/v1` | `/hitl/pending`, `/tech/degradation/snapshot`, `/admin/model-registry/models` | путь → канонический |
| другой ресурс | `/api/v1/routes` → `/api/v1/routes/inventory`; `/api/v1/admin/audit` → `/api/v1/audit/capability` | путь → живой канон |
| legacy-алиас | `/api/v1/users/all` → `/api/v1/user/all/` | канонический CRUD |
| эндпоинта нет | `/api/v1/admin/processes/active`, `/api/v1/admin/queues/summary`, `/api/v1/admin/prompt-versions/{n}/compare`, `/api/v1/admin/sql/query` | панель явно сообщает «endpoint не реализован» |
| эндпоинта нет, capability не подключена | guardrails-метрики, prompt-versions, webhook scheduler, storage list | панель явно сообщает; реализация — owner-задачи (§15) |

**Гейт.** `tests/unit/frontend/api_clients/test_api_contract_paths.py` теперь
сканирует и `pages/`: путь страницы обязан регистрироваться сервером,
зависимость от скрытых legacy-алиасов запрещена, динамические пути
(`f"/api/v1{path}"`) статически нерезолвимы и проверке не подлежат.

**Итог:** 22 вызова переведены на канонические пути (часть панелей реально
заработала), 17 панелей стали честными, регрессия «страница зовёт
несуществующий путь» закрыта гейтом.

---

## 2. Auth-контекст на WS- и GraphQL-поверхностях (ADR-0427)

**Дефект.** ADR-0421 закрыл проверку прав на action-поверхностях, но
`principal`/`permissions` передавались только в REST-инвокацию. WS
(`/ws/invocations`) собирал `InvocationRequest` без них, GraphQL
auto-schema — вызывал `dispatch_action` без них. Дополнительно аннотация
`info: "Info | None"` не распознавалась Strawberry как reserved-параметр
(`Info` был импортирован только под `TYPE_CHECKING`): `info` попадал в
GraphQL-схему как обычный аргумент, а auth-контекст в резолвер не доходил.

**Итог:** admin-action отклонялся даже для легитимного админа (fail-closed и
одновременно over-restrictive). Исправлено: сессия WS даёт `principal`/
`role:admin`, GraphQL-резолвер получает `info` как reserved-параметр и
передаёт права в action; `_permissions_from_info` переведён на канон
`resolve_action_permissions` (admin-роль → `role:admin`).

---

## 3. Tenant-фильтр для составных запросов — D-4 / G13 (ADR-0428)

**Дефект (critical).** ORM-фильтр добавляет предикат `tenant_id` к statement'у
верхнего уровня. У `CompoundSelect` (UNION/UNION ALL/INTERSECT/EXCEPT)
сущности живут в **ветвях**, у CTE — в отдельном определении: `_tenant_aware_entities`
возвращал `[]` → кросс-tenant чтение (под `tenant-a` `union_all` отдавал строки
`tenant-b`).

Прежние попытки (`replacement_traverse` без callback, пересборка
`CompoundSelect` через приватный API) были отклонены по делу: первая —
неверная сигнатура функции, вторая — приватный API.

**Итог:** patch-слой `_filter_statement` фильтрует ветви составных запросов и
определения CTE через публичный `sqlalchemy.sql.visitors.replacement_traverse`
(приватные атрибуты не используются). 4 кейса
`tests/unit/core/tenancy/test_tenant_filter_union_cte_d4.py` переведены из
strict-xfail в обычные тесты; фиксация «известного пробела» N-2 в
`test_reaudit_n1_n3_n4.py` заменена на проверку закрытой дыры. Проверено на
реальном SQLAlchemy 2.0.55 + SQLite. **G13 закрыт.**

---

## 4. Тестовая изоляция (ADR-0426)

Полный прогон давал **23 setup-ERROR** (0 failed) в двух файлах: pytest
резолвит dotted-путь патча через `getattr(parent, "sub")`, а у lazy-пакетов
(`core.config.services`) имя подмодуля в карте символов отсутствует; плюс
`test_no_audit_proxy.py` вычищал `sys.modules` без восстановления.

Итог: патчи — по объекту модуля (`monkeypatch.setattr(module, "attr", value)`),
`sys.modules` не чистится там, где это не требуется, изолированная загрузка
восстанавливает и `sys.modules`, и атрибуты реальных родителей.

---

## 4б. Функциональный smoke (локальный стенд из рабочего дерева, порт 8010)

| Проверка | Результат |
|---|---|
| `GET /health` | 200 |
| `GET /ready` | 200 |
| `GET /api/v1/user/all/` (канон портала) | 401 — маршрут есть (не 404) |
| `GET /api/v1/audit/capability` | 401 |
| `GET /api/v1/routes/inventory` | 401 |
| `GET /api/v1/admin/cron/list` | 401 |
| `GET /api/v1/admin/workflow-audit/events` | 401 |
| `GET /api/v1/tech/degradation/snapshot` | 401 |
| `GET /api/v1/admin/resilience-profiles` | 401 |
| `POST /graphql` | 401 (require_auth), роутер смонтирован |
| `POST /api/v1/auto/admin.get_config` | 401 (без токена), поверхность смонтирована |
| GraphQL auto-schema (вручную, 2 action'а) | поля `adminGetConfig`/`ordersCreate` → args только `payload`; псевдо-аргумента `info` нет |

Вывод: приложение стартует с правками волны 26; все канонические пути портала
зарегистрированы сервером (401 вместо прежних 404).

## 5. Регрессия

| Прогон | Результат |
|---|---|
| `tests/unit` (волна 25, до правок) | 0 failed, 23960 passed, **23 errors** |
| `tests/unit` (волна 26, полный) | **23994 passed, 180 skipped, 51 xfailed, 46 xpassed, 0 failed, 0 errors** (45:37; лог `.run/wave13-logs/reg_final_26b.txt`) |
| `tests/unit/core/` + `tests/unit/infrastructure/database/` | 7783 passed (после патча D-4) |
| `tests/unit/entrypoints/` + `tests/unit/api/` | 1743 passed (WS/GraphQL auth) |
| mypy-бюджет | 17 ошибок при бюджете 30 |
| ruff | чисто |
| docstrings | 0 missing |

## 6. Открытые owner-задачи (реестр — `docs/roadmap/OWNER_TASKS.md` §15)

1. `GuardrailsMetricsService` → DI + `GET /api/v1/admin/guardrails-metrics`.
2. `PromptRegistry` → list/activate/compare + `GET /api/v1/admin/prompt-versions*`.
3. `WebhookScheduler` → DI + `GET /api/v1/webhooks/scheduled`, `POST /api/v1/webhook/schedule` (SSRF-валидация).
4. `GET /api/v1/storage/list|get|download` (по ключу).
5. `GET /api/v1/admin/pools/snapshot`.
6. `GET /api/v1/admin/processes/active`, `GET /api/v1/admin/queues/summary`.
7. `POST /api/v1/admin/sql/query` — read-only SELECT с валидацией и аудитом (решение владельца).
8. Namespace фасадов (`plugin="system"`/`"core"`) — проверка идёт под namespace'ом вызывающего (ADR-0416 §Открытое).
9. Capability-декларации в `route.toml`/`plugin.toml` — автор обязан объявлять права.
