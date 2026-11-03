# ADR-0427 — Проброс principal/permissions на WS- и GraphQL-поверхности

* Статус: Accepted (2026-11-03, волна 26)
* Cycle: 186 (волна 26)
* Связан с:
  - ADR-0421 (права на action-поверхностях; `ActionMetadata.permissions`),
  - ADR-0422 (контракт клиент↔сервер),
  - ADR-0284 (новых межслойных нарушений не добавляем)
* Затрагивает:
  - `src/backend/entrypoints/websocket/ws_invocations.py`,
  - `src/backend/entrypoints/graphql/auto_schema.py` (auto-schema-резолверы),
  - `src/backend/entrypoints/graphql/schema.py` (`_permissions_from_info`),
  - `tests/unit/entrypoints/test_auth_propagation_ws_graphql.py` (новый)

---

## Контекст

ADR-0421 закрыл проверку прав на action-поверхностях: action с
`ActionMetadata.permissions` или с `admin`-префиксом требует соответствующего
права, иначе 403. Канон — `InvocationRequest.principal` / `.permissions`,
которые REST-поверхность (`POST /api/v1/invocations`) заполняет из
`AuthContext` через `resolve_action_permissions(auth)`.

Две другие поверхности эти данные не передавали:

1. **WS `/ws/invocations`.** `InvocationRequest` собирался без
   `principal`/`permissions`, хотя аутентифицированная сессия доступна
   (`websocket.state.ws_session`: `principal`, `is_admin`).
2. **GraphQL `/graphql`.** Живая поверхность — auto-schema
   (`build_auto_strawberry_schema`): резолвер вызывал `dispatch_action` без
   principal/permissions. Дополнительно аннотация `info: "Info | None"`
   не распознавалась Strawberry как reserved-параметр (`Info` был импортирован
   только под `TYPE_CHECKING`): `_is_reserved_type_str("Info | None")` не
   совпадает с допустимыми именами (`strawberry.Info`,
   `strawberry.types.info.Info`) → `info` попадал в GraphQL-схему как
   **обычный аргумент**, а auth-контекст в резолвер не доходил.

Итог: admin-action отклонялся даже для легитимного админа — одновременно
fail-closed (безопасно) и over-restrictive (функционально неверно: админ не
мог работать через WS/GraphQL).

---

## Решение

1. **WS:** сессия читается из `websocket.state.ws_session`; `principal`
   (только `str`) и `permissions` (`role:admin` при `is_admin is True`)
   передаются в `InvocationRequest`.
2. **GraphQL auto-schema:** резолвер получает `info` как **reserved-параметр
   Strawberry** — аннотация `info: Info[Any, Any]` (runtime-импорт
   `strawberry.types.Info`, eager-аннотации, т.к. в модуле намеренно нет
   `from __future__ import annotations`), и `info` добавлен в
   `resolver.__annotations__`. `principal`/`permissions` из
   `info.context["auth"]` уходят в `dispatch_action`.
3. **Канон прав единый:** `_permissions_from_info` переведён с
   `extract_user_permissions` на `resolve_action_permissions` — admin-роль из
   `metadata["admin_roles"]` добавляет `role:admin` (parity с REST/SOAP/WS).
   Невалидные значения ролей игнорируются (как в `extract_admin_roles`).

---

## Последствия

* Админ-action через WS/GraphQL доступен легитимному админу и по-прежнему
  недоступен анониму/не-админу (fail-closed сохранён).
* GraphQL-схема больше не содержит псевдо-аргумента `info`.
* Покрыто тестом `tests/unit/entrypoints/test_auth_propagation_ws_graphql.py`
  (4 теста: проброс в GraphQL, fail-closed без auth, `info` не аргумент,
  проброс в WS).
