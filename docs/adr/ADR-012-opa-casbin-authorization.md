# ADR-012: OPA + Casbin — двухуровневая авторизация

* Статус: accepted
* Дата: 2026-04-21
* Фазы: C6

## Контекст

- Необходим data-level policy: «такой-то route c таким payload →
  allow/deny по атрибутам».
- Параллельно нужен app-level RBAC/ABAC: роли users, matrix
  role×resource×action.
- Один инструмент покрывает хуже, чем два специализированных.

## Решение

1. **OPA** (Open Policy Agent) — data-level. Политики в Rego
   (внешние файлы, mount через ConfigMap в K8s). Интеграция через REST
   (`POST /v1/data/<policy>`), `OPAClient` в `policy/opa.py`.
   **Fail-closed** при недоступности OPA.
2. **Casbin** — app-level RBAC/ABAC. Модель в
   `policies/casbin_model.conf`, policy-store файл или DB (для
   hot-reload). `CasbinAdapter` в `policy/casbin_adapter.py`.
3. DSL API: `.with_opa_policy("routes/orders/read")`,
   `.with_casbin_role("orders_reader")`.
4. Policy-middleware FastAPI применяет OBA (опционально) и Casbin
   (обязательно) до route.

## Альтернативы

- **Только OPA**: app-level тоже можно писать на Rego, но сложнее
  change-management на команды разработки.
- **Только Casbin**: нет гибкости OPA на data-level.
- **Закрытые решения (Okta, Auth0)**: отвергнуто — политики не
  версионируются вместе с кодом.

## Последствия

- Кластер обязан иметь OPA-sidecar (или shared-service).
- Любой прод-route проходит через два уровня проверок.
- Логи policy-decision — обязательные для аудита (в OpenTelemetry span).
