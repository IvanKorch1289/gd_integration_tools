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


---

## 2026-09-09 — dev_light live-верификация (positive auth UNBLOCKED, M6-#3)

Стенд: `APP_PROFILE=dev_light APP_SERVER=uvicorn manage.py run --port 8001`
(без docker; SQLite ./.run/dev.sqlite3; redis/mq — in-memory fallbacks).
Пользователь: dev_admin (создан локально в dev-SQLite, argon2id по схеме
модели). Секрет JWT: SecureSettings.secret_key (профиль dev_light).

### Исправленные prod-блокеры (эта сессия)
1. **catch-22 B-04**: auth_required требовал Bearer на /auth/login до
   step-up → 401 на любой логин. Login path возвращён в public-префиксы.
2. **audit_replay._collect_body** ждал http.disconnect после потреблённого
   upstream body → 30-90с «зависание» (задержка = таймаут curl клиента).
   Fix: bounded wait 1s/chunk.
3. **request_log._get_request_body** fallback потреблял receive → FastAPI
   получал disconnect → 422 «Field required: body». Fix: fallback убран,
   логируется placeholder.
4. **JWT secret**: login звал jwt_encode без secret → 500 на каждом
   успешном логине. Fix: secret из SecureSettings (= JwtBackend DI).
5. **Двойное маскирование ответа**: data_masking (580) + pii_masking_response
   (700) маскировали access_token → клиент получал «***». Fix: token-issuer
   пути исключены из обоих.

### Команды и ответы (verified 2026-09-09)

```bash
# Позитивный логин (200, JWT):
$ curl -s -X POST http://localhost:8001/api/v1/auth/login \
    -H "Content-Type: application/json" -H "X-Step-Up-Token: dev-probe" \
    -d '{"method":"password","username":"dev_admin","password":"..."}'
{"access_token":"eyJ...","token_type":"bearer","auth_method":"password",
 "username":"dev_admin","is_superuser":true,"expires_in":3600}          # 200, 0.35-0.6s

# Защищённый REST с JWT (auth пройден; 403 = RBAC-контракт):
$ curl -s -H "Authorization: Bearer $TOKEN" .../api/v1/admin/certs/expiring
403 {"detail":{"code":"admin_role_required",
     "required":["operator","read_only","super_admin"],"actual":[]}}

# Негатив: без токена → 401; инвалидный токен → 401 (verified).
# GraphQL POST /api/v1/graphql c JWT → проходит auth, доходит до валидации
#   контракта (422 query/request — multipart-контракт graphql-upload).

### Осталось для полного покрытия метрики №11
- WS/SSE/MQTT/MQ/gRPC функциональные прогоны (нужны специализированные
  клиенты; gRPC — grpc-serve на unix socket, manage.py grpc-serve).
- Браузерные проверки Swagger/GraphQL playground/Streamlit.
- step-up-request endpoint (docstring LoginStepUpMiddleware; токен сейчас
  presence-checked, не подписан) — реализовать выпуск+валидацию.


### 2026-09-09 (доп.): B-04 flow ПОЛНОСТЬЮ РАБОТАЕТ live — step-up-request реализован

**Реализовано** (коммит 8747e2635+): POST /api/v1/auth/step-up-request —
выпуск подписанного HMAC-SHA256 токена (TTL 600s, IP-binding, nonce);
LoginStepUpMiddleware (order 650, WIRED в setup_middlewares) валидирует
подпись+expiry+IP вместо presence-check; CSRF safe-path, auth_required
public prefix, api-key exemption — для pre-auth issuance.

**Живая последовательность (verified 2026-09-09, порт 8002)**:

```bash
# 1. Login без step-up → 401 (guard активен):
$ curl -s -o /dev/null -w "%{http_code}" -X POST .../api/v1/auth/login \
    -H "Content-Type: application/json" -d '{"method":"password",...}'
401

# 2. Выпуск step-up токена → 200, token_len=161:
$ curl -s -X POST .../api/v1/auth/step-up-request
{"step_up_token":"eyJpcCI6IjEyNy4wLjAuMSIsImV4cCI6...","token_type":"step_up","expires_in":600}

# 3. Login с токеном → 200 + JWT (212 chars, unmasked, 0.18s):
$ curl -s -X POST .../api/v1/auth/login -H "X-Step-Up-Token: $ST" -d '{...}'
{"access_token":"eyJ...","username":"dev_admin","is_superuser":true,...}

# 4. Подделка токена (добавлен 'zzz' → подпись невалидна) → 401 ✓
#    (IP-binding + HMAC validation работают live)

# 5. Защищённый REST с JWT → 200 (readiness, 3ms);
#    без JWT → 401; RBAC-контракт: certs/expiring → 403 admin_role_required
```

**Статус протоколов (metric #11)**: REST (positive+negative) ✓;
GraphQL auth-pass ✓ (422 = multipart-контракт graphql-upload — документировать);
WS/SSE-stream/gRPC/MQTT/MQ — требуют специализированных клиентов
(manage.py grpc-serve, ws-клиент) — след. сессия.
