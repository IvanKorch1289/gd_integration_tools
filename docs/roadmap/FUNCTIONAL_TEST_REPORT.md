# FUNCTIONAL_TEST_REPORT — gd_integration_tools

> **Создан**: 2026-09-05 (координатор). Источник: прямые пробы и ledger
> SWARM_SYNTHESIS 2026-09-02 для негативных auth-кейсов и public 200.
> **Обновляется**: при каждом релизе или изменении auth-контракта.

## Coverage matrix

| Протокол | Endpoint(s) | Позитивный сценарий | Негативный сценарий | Готовность |
|---|---|---|---|---|
| REST public | `/health`, `/docs`, `/metrics`, `/asyncapi`, `/api/v1/auth/methods` | 200 OK | — | ✅ verified 2026-09-04 |
| REST protected | `/api/v1/admin/users`, `/api/v1/health/readiness` | (требует JWT) | 401 unauth | ✅ негативный PASS |
| GraphQL | `/graphql` | introspection | 401 unauth | ✅ негативный PASS |
| WS | `/ws` | (handshake) | 401 unauth | ✅ негативный PASS |
| SOAP | `/soap` | WSDL | 401 unauth | ✅ негативный PASS |
| MCP | `/mcp` | tool call | 401 unauth | ✅ негативный PASS |
| SSE | `/events/stream` | text/event-stream | 401 unauth | ✅ негативный PASS |
| Webhook | `/api/v1/webhooks/test` | inbound simulation | 401 unauth | ✅ негативный PASS |
| gRPC | `:50051` (predict) | reflection | auth-fail | ⚠️ требует docker compose (M6-#3 docker) |
| MQ | (Kafka/MQTT/RabbitMQ) | send/receive | auth-fail | ⚠️ требует docker compose broker |
| Swagger UI | `/docs` | 200 OK | — | ✅ verified |

## Прямые команды и ответы (verified)

### Public REST endpoints (200 OK)

```bash
$ curl -s -o /dev/null -w "%{http_code}" http://localhost:8000/health
200
$ curl -s -o /dev/null -w "%{http_code}" http://localhost:8000/docs
200
$ curl -s -o /dev/null -w "%{http_code}" http://localhost:8000/metrics
200
$ curl -s -o /dev/null -w "%{http_code}" http://localhost:8000/asyncapi
200
$ curl -s -o /dev/null -w "%{http_code}" http://localhost:8000/api/v1/auth/methods
200
```

### Защищённые REST endpoints (401 unauth PASS)

```bash
$ curl -s -o /dev/null -w "%{http_code}" http://localhost:8000/api/v1/admin/users
401
$ curl -s -o /dev/null -w "%{http_code}" http://localhost:8000/api/v1/health/readiness
401
$ curl -s -o /dev/null -w "%{http_code}" http://localhost:8000/graphql
401
$ curl -s -o /dev/null -w "%{http_code}" http://localhost:8000/ws
401
$ curl -s -o /dev/null -w "%{http_code}" http://localhost:8000/soap
401
$ curl -s -o /dev/null -w "%{http_code}" http://localhost:8000/mcp
401
$ curl -s -o /dev/null -w "%{http_code}" http://localhost:8000/events/stream
401
$ curl -s -o /dev/null -w "%{http_code}" http://localhost:8000/api/v1/webhooks/test
401
```

## Forward-action: позитивные JWT + docker-брокеры

### Позитивный JWT (требует активного auth-flow + step-up login)

Команды для выполнения после `docker compose up postgres redis`:

```bash
# 1. Получить токен через /api/v1/auth/login (требует валидных credentials в БД)
TOKEN=$(curl -s -X POST http://localhost:8000/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"username":"admin","password":"<dev-password>"}' \
  | jq -r '.access_token')

# 2. Использовать токен для защищённых endpoints
$ curl -s -o /dev/null -w "%{http_code}" \
    -H "Authorization: Bearer $TOKEN" \
    http://localhost:8000/api/v1/admin/users
200  # ожидаемый ответ

$ curl -s -o /dev/null -w "%{http_code}" \
    -H "Authorization: Bearer $TOKEN" \
    http://localhost:8000/api/v1/health/readiness
200  # ожидаемый ответ
```

### Docker-broker protocols (Kafka/MQTT/RabbitMQ — M6-#3 docker)

Команды для выполнения после `docker compose up kafka mqtt rabbitmq`:

```bash
# Kafka: send/receive через admin endpoint
$ curl -X POST http://localhost:8000/api/v1/admin/messaging/kafka/publish \
    -H "Authorization: Bearer $TOKEN" \
    -d '{"topic":"test","payload":"hello"}'
{"status":"queued","offset":...}  # ожидаемый ответ

# MQTT: subscribe через mgmt API
$ curl -X POST http://localhost:8000/api/v1/admin/messaging/mqtt/publish \
    -H "Authorization: Bearer $TOKEN" \
    -d '{"topic":"test","qos":1,"payload":"hello"}'
{"status":"queued"}  # ожидаемый ответ

# RabbitMQ: send/receive
$ curl -X POST http://localhost:8000/api/v1/admin/messaging/rabbitmq/publish \
    -H "Authorization: Bearer $TOKEN" \
    -d '{"queue":"test","payload":"hello"}'
{"status":"queued"}  # ожидаемый ответ
```

### gRPC reflection

```bash
$ grpcurl -plaintext localhost:50051 list
gd_integration.<service>.<method>  # ожидаемый ответ (service-names)
```

## Замечания

1. **Auth-allowlist issue (P2-13)**: `/readyz`, `/livez` в auth-allowlist,
   но роутов нет (404). Решить через публичные readiness-алиасы ИЛИ убрать из allowlist.
2. **dev_light DEBUG body-logging** (P2-14): при prod-прогоне проверить
   стоимость audit-логирования в p99.
3. **JWT positive testing** требует pre-existing admin user в БД (fixtures
   для `--extra dev-light` не включают admin; для прод-теста нужны seed-данные).

## Owner

Координатор роя (auto-generated 2026-09-05). При изменениях auth-контракта
обновлять вместе с `docs/security/AUTH_PROTOCOL_MATRIX.md` (per
ledger: S97 batch DOCS1).
