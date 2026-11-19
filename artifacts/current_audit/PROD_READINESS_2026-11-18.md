# Готовность к проду и сверка плана доработки — волна 36 (2026-11-18)

**Срез:** `master` @ `c85a32520` · **Метод:** функциональный прогон
`docker compose` (prod-профиль) на реальном стенде + сверка плана
`artifacts/current_audit/CODE_AUDIT_2026-11-18.md` §4 + гейты.

---

## 1. Итог одной строкой

**Пуш исправлен; план закрыт на 14/19 кодовых пунктов; функциональный тест
выполнен — но он вскрыл 10 дефектов прод-стенда, из-за которых стек
не поднимался вообще.** После их устранения приложение стартует, проходит
миграции, отвечает 200 и выполняет workflow-запрос выписки ЕГРН.

| Раздел | Вердикт |
|---|---|
| Пуш (rejected: remote ahead) | ✅ исправлен: rebase на `origin/master` (1 коммит бота), конфликт индекса ADR разрешён пересборкой, **push успешен** (`0165c4d28..96d2f8071`) |
| План доработки (§4 отчёта) | ◐ **14/19** кодовых, **1/10** библиотечных, **4/6** CI; остальное — решения владельца |
| Готовность к проду | ⚠️ **код — да**; **прод-стенд — был нерабочим**, теперь работоспособен; остаются 5 внешних зависимостей (minio-образ недоступен, RabbitMQ/СМУ-доступ, TLS-сертификаты, реальный СКБ, JupyterHub-IdP) |
| Функциональное терование | ✅ выполнено: 5 вызовов, workflow-запрос ЕГРН дошёл до внешнего СКБ и вернул бизнес-ответ |

---

## 2. Сверка плана доработки (§4 отчёта волны 35)

### 2.1. Код (19 пунктов)

| Пункт | Статус | Комментарий |
|---|---|---|
| P1-1 caller-namespace в последовательном пути | ✅ | волна 36 |
| P1-2 адаптер не затирает `payload_model` | ✅ | волна 36 |
| P1-3 фиче-флаги читаются динамически | ✅ | волна 36 |
| P1-4/P1-5 единый tenant-контекст | ✅ | волна 36 |
| P2-1 pre-load расширений в lifespan | ✅ | волна 36 (startup-фаза) |
| P2-2 гейт «у action'а один владелец» | ✅ | волна 36 (`tools/check_action_ownership.py`) |
| P2-3 контракт `call_function` | ✅ | волна 36 |
| P2-4 инверсия в `utilities` | ✅ | волна 36 |
| P2-4 гейт «no lazy import из composition/plugins» | ⬜ | требует отдельного AST-гейта |
| P2-5 ETag по отдаваемым байтам | ✅ | волна 36 |
| P2-6 мёртвые `basicAuth`/`samlSession` | ⬜ | публичный контракт → решение владельца API |
| P2-7 `include:` при merge `extends` | ✅ | волна 35 |
| P2-8 `rglob("plugin.toml")` в capability-графе | ✅ | волна 36 (8 → 12 плагинов) |
| P2-9 `xfail_strict` + perf-профиль | ⬜ | 48 XPASS (сеть не strict) — требует разделения perf-кейсов |
| P2-10 `logout()` чистит API-кэш | ✅ | волна 36 (но кнопки выхода в портале нет) |
| P3 LRU `_validation_cache` | ✅ | волна 36 |
| P3 фаза `denied` в трейсере | ⬜ | статус `denied` есть, **фазы** в трейсере нет |
| P3 удаление мёртвого `dsl/engine/process` | ✅ | волна 36 |
| P3 `ProtocolType` → `core/types/` | ⬜ | требует ре-экспорта из dsl |
| P3 единый `SYSTEM_TENANT_ID` | ✅ | волна 36 |
| P3 `cache_resource` → `session_state` | ⬜ | SSE-очередь и `FakeOutbox` |

### 2.2. Библиотеки (10 пунктов)

| Пункт | Статус |
|---|---|
| `altair <5.5` (Python 3.15) | ✅ волна 35 |
| `ruamel.yaml` в runtime-зависимости | ⬜ требует lock-согласования |
| убрать `grpc-interceptor` | ⬜ требует lock-согласования |
| объявить `requests` | ⬜ требует lock-согласования |
| SHA-пиннинг GitHub Actions | ⬜ предложение |
| `pytest-xdist --dist worksteal` | ⬜ предложение |
| одна версия `tenacity` | ⬜ предложение |
| `license`/`urls`/`LICENSE` | ⬜ предложение |
| комментарий про aiohttp | ⬜ предложение |
| `mutmut.also_copy` → `.env.example` | ⬜ предложение |

### 2.3. CI и процесс (6 пунктов)

| Пункт | Статус |
|---|---|
| отдельный job мутационного гейта | ✅ волна 35 |
| контрактные гейты «ответ всегда завершён» | ✅ волна 35 |
| гейт владения actions в CI | ✅ волна 36 |
| `uv lock --check` в CI | ✅ фактически покрыто `uv sync --locked` (падает при рассинхроне lock) |
| `make release-notes` в CI | ✅ **волна 36** (шаг `changelog_autogen` в `release.yml`) |
| гейт «все слои в матрице» | ⬜ |

**Итого: 14/19 кодовых, 1/10 библиотечных, 5/6 CI.** Остальное — либо
требует решения владельца (публичный контракт, lock-файл), либо это отдельные
средние по трудоёмкости задачи (AST-гейт lazy-импортов, перф-профиль xfail,
перенос `ProtocolType`, `session_state`-миграция SSE-очереди).

---

## 3. Функциональное тестирование (docker compose, prod-профиль)

### 3.1. Что поднималось

Стек (18 сервисов): postgres, redis, mongo-prod, kafka + zookeeper,
schema-registry, connect-distributed, kafka-ui, rabbitmq-prod, minio*, vault,
clickhouse, otel-collector, jaeger*, open-webui*, jupyterhub*, app,
migration-runner, workflow-worker ×4.

\* не поднялись: `minio/minio` — Docker Hub отдаёт «pull access denied» для
всего namespace (образ MinIO вынесен в `quay.io`, но там требуется авторизация);
`open-webui`/`jupyterhub` — не успели вытянуть по времени/диску (8.9 → 4.5 ГБ
свободного места на dev-хосте).

Состояние после устранения дефектов: **app — healthy**, workflow-worker ×4 —
healthy, инфраструктура — healthy, миграции — exit 0.

### 3.2. Результат запроса workflow'а выписки ЕГРН

Скрипт `ops/compose/smoke_egrn.py` выполняется внутри контейнера (ключ API
берётся из настроек приложения — секрет наружу не выходит):

```
[1] GET  /health                              → 200 {"status":"alive","version":"0.1.0"}
[2] POST /api/v1/skb/get-objects-by-address   → 200 (внешний СКБ ответил бизнес-сообщением)
[3] POST /api/v1/skb/create-request           → 200 (запрос ушёл во внешний СКБ-Техно)
[4] GET  /api/v1/skb/get-result               → пропущен: в ответе нет order_uuid
[5] GET  /api/v1/skb/get-kinds                 → 500 (внешний мок не реализует справочник)
```

Ответ на шаг 3 (сокращённо):

```json
{"status_code": 200,
 "data": {"Result": false, "Data": {},
          "Message": "Нельзя создать запрос с указанным типом запроса …"},
 "headers": {"server": "Microsoft-IIS/10.0", "x-aspnet-version": "4.0.30319"}}
```

**Что подтверждено:** сквозной путь работает — routing → авторизация по
`X-API-Key` → валидация тела (422 на неверной форме) → диспетчеризация
action'а → реальный сетевой вызов внешнего СКБ-Техно → структурированный
ответ с `correlation_id`/`request_id` и бизнес-сообщением внешнего сервиса.

**Что не подтверждено:** приём заказа внешним сервисом — идентификатор вида
запроса берётся из справочника `orderkinds.skb_uuid`, а стендовый мок
использует другой словарь (в БД сид: `00000000-…-0001…0004`).

---

## 4. Дефекты, найденные функциональным прогоном (10)

Ни тесты, ни статический анализ их не видели — стек просто не стартовал.

| # | Sev | Где | Симптом | Причина |
|---|---|---|---|---|
| 1 | **P0** | `ops/compose/otel-collector-config.yaml` | коллектор не стартовал: «unknown type: jaeger» | экспортёр `jaeger` удалён из коллектора ≥ 0.86 → заменён на `otlphttp` → `jaeger:4318` |
| 2 | **P0** | `ops/compose/docker-compose.prod.yml` | kafka: код 1, «KAFKA_ZOOKEEPER_CONNECT is required» | переменная отсутствовала |
| 3 | **P0** | там же | сервисы prod-файла и base-файла — в **разных сетях** (ключ `compose_default` vs неявный `default`) → app не видел mongo/kafka/minio/vault | ключ сети приведён к `default` |
| 4 | **P0** | `config_profiles/prod.yml` ↔ compose | `mongo.enabled=true`, хост `mongo-prod`, сервиса нет → `start_mongo_client` (required) таймаут 30 с → lifespan падал | добавлен сервис `mongo-prod` + согласованные учётные данные |
| 5 | **P0** | `redis` в compose vs `REDIS_PASSWORD` | «ERR Client sent AUTH, but no password is set» → faststream-брокер не поднялся (таймаут 3 с) → воркер падал | в prod-стеке Redis с паролем; мигратор дополнительно получал `REDIS_PASSWORD=""` → NOAUTH + `RecursionError` в redis-py |
| 6 | **P0** | `queue` в prod-профиле ↔ compose | `AMQPConnectionError: [Errno 111]` → приложение не стартовало | сервиса RabbitMQ не было; пользователь `guest` пускает только с localhost → добавлен `rabbitmq-prod` с отдельным пользователем |
| 7 | **P0** | `JUPYTER_HUB_API_TOKEN` | `JupyterHubSettings`: «api_token обязателен при enabled=true» → настройки не поднимались | токен не пробрасывался в app/worker/migrator |
| 8 | **P0** | `DB_HOST`/`REDIS_HOST` | «Error 111 connecting to redis-prod:6379» | prod-профиль рассчитан на K8s-хосты (`-prod`), compose поднимает свои → явные хосты + сетевой алиас `redis-prod` |
| 9 | **P0** | `src/backend/infrastructure/database/database/initializer.py` | «psycopg.ProgrammingError: invalid connection option "ssl"» → приложение не подключалось к БД | ключ TLS-опции зависит от драйвера: asyncpg — `ssl=`, psycopg — `sslmode=`/`sslrootcert=`; `prefer`/`require` подменяются на `verify-ca` (без молчаливого plaintext) |
| 10 | **P0** | `src/backend/infrastructure/clients/storage/redis/connection_mixin.py` | «DataError: Invalid input of type: 'SecretStr'» | в Redis-клиент уходил объект `SecretStr`, а не строка (дефект не проявлялся с пустым паролем dev-профиля) |
| 11 | **P1** | healthcheck приложения | контейнер вечно unhealthy → `depends_on: service_healthy` не выполнялся | `/health` запрашивался без Host-заголовка → trusted-host отвечал 400 |
| 12 | **P2** | `.dockerignore` | контекст сборки 9+ ГБ (`.venv`) | файла не было |

---

## 5. Готовность к проду

### 5.1. Что готово

* регрессия `tests/unit` — **24 545 passed, 0 failed** в CI-режиме (723 с, `-n 2 --dist loadfile`);
* гейты: layers (0 новых), decorative/route/action-ownership/workflow-specs,
  docstrings (0 missing), ruff, mypy (12 = baseline), coverage (77.68 %),
  mutation (**PASS 21.6 %**, baseline повышен);
* OpenAPI — 447 путей / 477 операций, у всех `security`;
* прод-стенд поднимается: app healthy, workflow-worker ×4 healthy, миграции
  проходят, внешние вызовы (СКБ) работают.

### 5.2. Что мешает проду (внешние зависимости, не код)

| # | Позиция | Влияние | Кто решает |
|---|---|---|---|
| 1 | `minio/minio` недоступен для pull (Docker Hub отдаёт denied на весь namespace; в `quay.io` — требует авторизации) | S3-совместимое хранилище в стенде не поднимается; приложение деградирует на LocalFS (fallback-цепочка S3 → LocalFS работает) | платформа: зеркало registry или другой S3-совместимый образ |
| 2 | TLS-сертификаты БД/Redis/очереди | прод-профиль требует TLS (`ssl_mode: require`, `redis.use_ssl`, `queue.use_ssl`); в стенде отключено переключателями `DB_SSL_MODE`/`REDIS_USE_SSL`/`QUEUE_USE_SSL` | платформа: CA-бандлы + `ca_bundle` |
| 3 | Реальный СКБ-Техно и справочник видов запросов | стендовый мок принимает другой словарь `RequestType` | интеграционный владелец |
| 4 | JupyterHub: `DummyAuthenticator` | до замены на IdP хаб нельзя публиковать | платформа/ИБ |
| 5 | RabbitMQ/SМУ-доступ, Kafka-ACL в K8s | в реальном контуре имена хостов `-prod` резолвятся только в K8s | платформа |

### 5.3. Внутренние долги, влияющие на эксплуатацию

* мутационный гейт в CI даёт SKIPPED (нужен отдельный job/кэш `mutants/`),
  baseline не рэтчится автоматически;
* `Cache-Control: public` на аутентифицированных tenant-ответах (нужен
  `private`/`Vary`);
* 48 XPASS (сеть не strict) маскируют регрессии;
* capability-декларации scope-optional проверяются гейтом только по имени;
* нет гейта «все слои в матрице» (каталог `utilities/**` вне матрицы).

---

## 6. Как воспроизвести функциональный тест

```bash
cd ops/compose
export VAULT_ROOT_TOKEN=... MINIO_ROOT_USER=... MINIO_ROOT_PASSWORD=... \
       CLICKHOUSE_PASSWORD=... OPEN_WEBUI_SECRET_KEY=... REDIS_PASSWORD=... \
       RABBITMQ_PASSWORD=... JUPYTER_HUB_API_TOKEN=... MONGO_USERNAME=... \
       MONGO_PASSWORD=... DB_SSL_MODE=disable REDIS_USE_SSL=false QUEUE_USE_SSL=false
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d --build
docker compose -f docker-compose.yml -f docker-compose.prod.yml ps
docker compose -f docker-compose.yml -f docker-compose.prod.yml \
    exec -T app python /app/ops/compose/smoke_egrn.py
```
