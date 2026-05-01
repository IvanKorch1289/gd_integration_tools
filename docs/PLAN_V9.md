# МАСТЕР-ПРОМПТ V9 — gd_integration_tools
## Сводный план: все Wave от 0 до 34 + правила (краткая версия)

> **Замещает**: v7, v8, v8-amendment — единый компактный документ.
> **Назначение**: операционный план для команды. Каждый Wave — 2-6 строк описания + критерии.
> Детали подшагов берутся из v8 / v8-amendment при необходимости.

---

# I. ОБЯЗАТЕЛЬНЫЕ ПРАВИЛА

## ⚠️ ОСНОВНЫЕ РОЛИ
**5 ролей** на каждом шаге: СД (системный дизайнер), РАЗ (разработчик), ДО (DevOps), АН (аналитик), ТЕС (тестировщик).

## ПРАВИЛО 0 — ИНИЦИАЛИЗАЦИЯ ШАГА
```bash
graphify update . && graphify query <модули>
cat .claude/DECISIONS.md .claude/KNOWN_ISSUES.md
python tools/check_layers.py
```

## ПРАВИЛО 0 — ВСЕГДА ИЗНАЧАЛЬНО УТОЧНЯЙ ДЕТАЛИ
Не трать зря токены на ответ, который нужно будет переделать на 90%

## ПРАВИЛО 1 — ОДИН ШАГ ЗА РАЗ
Не переходить к следующему без всех критериев. Не рефакторить вне шага.

## ПРАВИЛО 2 — ПАРАЛЛЕЛЬНЫЕ АГЕНТЫ
Независимые подшаги — параллельные субагенты. Главный агент собирает результаты.

## ПРАВИЛО 3 — DOCSTRING (русский)
Каждый Python-файл/класс/публичный метод — краткий русский docstring + Args/Returns/Raises. Запрещены пустые `"""TODO"""`.

## ПРАВИЛО 4 — LAYER POLICY
```
entrypoints/    → services/, schemas/
services/       → core/, schemas/
infrastructure/ → core/
core/           → stdlib, pip
plugins/        → все
```
Запрещено: core→infra/services/entry; services→infra напрямую; entrypoints→infra напрямую.

## ПРАВИЛО 5 — КОММИТЫ
`git commit -m "wave{N}.{M}: {описание}"` + `graphify update .` после.

## ПРАВИЛО 6 — REDIS POLICY
Только горячие данные с TTL. Постоянное → PostgreSQL/MongoDB/Vault/ClickHouse. Snapshots/audit/sessions — НЕ Redis.

## ПРАВИЛО 7 — ЗАПРЕТЫ
- `aiohttp`, `prefect`, `pandas` в DSL/utilities
- Кастомные TTL-словари (только cachetools)
- Push без подтверждения
- Вызывать infra из core напрямую

## ПРАВИЛО 8 — РИТУАЛ ОБСУЖДЕНИЯ (перед каждым Wave)
4 параллельных субагента (СД/АН/ДО/ТЕС) → отчёт заказчику с 3 расхождениями + 2-3 доп.предложениями → ожидание «ОК».

## ПРАВИЛО 9 — DEV-MODE FALLBACK
Любой prod-компонент имеет dev-аналог: PG→SQLite, Redis→cachetools, S3→LocalFS, Vault→.env+keyring, CH→SQLite-jsonb, Mongo→TinyDB, ES→SQLite-FTS5, Kafka→Redis-Streams, ClamAV→hash-skip, Prometheus→JSON-файл, Sentry→ROTATING_FILE.

## ПРАВИЛО 10 — БОЛЬШИЕ ЗАПРЕТЫ
- Новый протокол-приёмник без DSL-Source
- Новый коннектор без DSL-Sink
- Зависимость без проверки текущего стека
- Запуск Wave без Правила 8

## ПРАВИЛО 11 — RPA SECURITY
Side-effect шаги → `compensate` или `irreversible: true`. Sandbox `none` запрещён в prod для script/desktop. PII в evidence — только шифрованно. Секреты — через `secret_ref`.

## ПРАВИЛО 12 — DOCS-AS-CODE
Новый DSL-процессор без записи в `docs/reference/dsl/` → CI красный. Settings без `Field(description=...)` → CI красный. ADR обязателен для решений, влияющих на >2 слоя.

## 🌟 ПРАВИЛО 13 — БОРЬБА С ОВЕРИНЖИНИРИНГОМ + GATEWAY (НОВОЕ, ОБЯЗАТЕЛЬНОЕ)

### 13.1. Anti-overengineering checklist (для каждого PR)
Перед коммитом РАЗ обязан ответить «нет» на все вопросы:

1. **Можно ли решить меньшим кодом?** — есть ли существующая абстракция?
2. **Все ли слои абстракции нужны?** — нет ли фабрики ради фабрики, обёртки ради обёртки?
3. **Все ли публичные API используются?** — мёртвый API = долг.
4. **Не дублирую ли существующее?** — `grep` похожих имён/функций перед написанием.
5. **Можно ли заменить кастомный код библиотекой?** — если в стеке нет библиотеки, проверить `pyproject` доп.экстры.
6. **Нет ли преждевременной обобщённости?** — параметризация «на будущее» = тех.долг сегодня.
7. **Нет ли «магии»?** — динамические импорты, мета-классы, monkey-patch — только с ADR-обоснованием.

Если **хотя бы один** ответ «да» — упростить ДО реализации, не после.

### 13.2. GATEWAY-правило (ключевое)

**Определение**: если две или более функции/класса/модуля решают **логически близкие задачи** — они должны быть консолидированы в **единый Gateway** с явной taxonomy.

**Существующие/плановые Gateway проекта**:

| Gateway | Объединяет | Контракт |
|---|---|---|
| `Invoker` (W22) | Sync/Async/Deferred/Background/Streaming запуск | `InvocationRequest → InvocationResult` |
| `NotificationGateway` (W8.3) | Email/Telegram/Slack/Teams/SMS/Express | `Notification → NotificationResult` |
| `SourceRegistry` (W23) | HTTP/SOAP/gRPC/WS/Webhook/MQ/CDC/Watcher/Polling | `Source.start(on_event)` |
| `SinkRegistry` (W23) | HTTP/SOAP/gRPC/MQ/Mail/SMS/RPA-Sinks | `Sink.send(payload)` |
| `ResourceManager` (W28.0) | Browser/SSH/COM/DB-сессии | `acquire(kind) → Resource` |
| `CacheBackend` (W2.2) | Redis/KeyDB/Memcached/Memory | `get/set/delete/lock` |
| `ObjectStorage` (W2.3) | S3/MinIO/LocalFS | `put/get/delete/list` |
| `Antivirus` (W2.4) | ClamAV unix/tcp/HTTP | `scan(file) → result` |
| `CertStore` (W2.1) | Vault/PostgreSQL/Memory | `set/get/history` |
| `SecretsBackend` (W21) | Vault/.env+keyring | `resolve(ref) → value` |
| `AuditBackend` (W21/W5) | ClickHouse/SQLite | `record(event)` |
| `DocStoreBackend` (W21) | MongoDB/TinyDB | `aput/aget/asearch/adelete` |
| `SearchBackend` (W21) | Elasticsearch/SQLite-FTS5 | `index/search/delete` |
| `MQBackend` (W21) | Kafka/RabbitMQ/NATS/Redis-Streams/Memory | `publish/subscribe` |
| `MetricsBackend` (W21) | Prometheus/JSON-file | `record_metric(name, value)` |
| `ActionDispatcher` (W14.1) | Все бизнес-действия независимо от транспорта | `dispatch(action_id, payload)` |
| `ExecutionBackend` (W13.4) | Local/TaskIQ/Dask | `submit(task) → future` |
| `ImportGateway` (W24) | Postman/OpenAPI/WSDL → Connector | `import(spec) → ConnectorSpec` |
| `RPABrowserBackend` (W28.1) | Playwright/Patchright/Selenium | `session(config) → BrowserSession` |
| `RPADocBackend` (W28.5) | python-docx/openpyxl/pptx/pypdf/pdfplumber/pymupdf | универсальный read/write |
| `LLMBackend` (W29) | OpenAI/Anthropic/local + MCP | `complete(prompt) → response` |

### 13.3. Правила введения нового Gateway

**Триггер**: добавляем 2-й или 3-й конкретный backend для одной функциональной области.

**Процесс**:
1. **Согласование с заказчиком**: до реализации **обязательно** запрос `[АН → ЗАКАЗЧИК] Gateway proposal: X объединяет {A, B, C}, контракт: …, миграция: …, риск: …`
2. ADR-документ (`docs/adr/ADR-XXX-{gateway-name}.md`)
3. ABC в `core/interfaces/{gateway}.py`
4. Конкретные backends в `infrastructure/{area}/backends/`
5. Factory + DI в `infrastructure/{area}/factory.py`
6. Миграция всех существующих использований на Gateway
7. Удаление старых прямых импортов

### 13.4. Запреты Gateway-правила

- ❌ **НЕЛЬЗЯ** делать Gateway «на будущее» (преждевременно). Только когда уже **есть 2-й конкретный backend** или ясно, что появится в текущем Wave.
- ❌ **НЕЛЬЗЯ** объединять под одним Gateway функции **разной семантики** (anti-pattern: «UniversalManager» с 50 методами).
- ❌ **НЕЛЬЗЯ** делать Gateway **без согласования с заказчиком**, если он влияет на публичный API или конфигурацию.
- ❌ **НЕЛЬЗЯ** держать «дубль вне Gateway» — если функция логически входит в область — она внутри Gateway, иначе это нарушение.
- ✅ **МОЖНО** и **НУЖНО** консолидировать в Gateway даже один backend, если **по контексту** очевидно появление второго в плане (W23 SourceRegistry создаётся сразу для 10 источников).

### 13.5. Aудит Gateway (на каждом Wave)
```bash
python tools/check_gateways.py
# → 0 «orphan» backends (которые могли бы быть в Gateway, но не интегрированы)
# → 0 дубликатов методов между Gateway и legacy-кодом
# → каждый Gateway имеет ADR
```

---

# II. КАРТА ВСЕХ WAVE

## ✅ ЗАВЕРШЁННЫЕ (по аудиту 28.04.2026)
- **W0** Фундамент + устранение ~1100 LOC оверинжиниринга (~90%)
- **W1** Архитектурный фундамент (ABC, layer linter, Redis audit)
- **W2** Инфраструктурный слой (CertStore, Cache, LocalFS, ClamAV)
- **W3** DSL Core (3.1–3.8: pipeline, processors, redirect, dedup, multicast, bidirectional YAML)
- **W4** Express BotX DSL (client + 7 процессоров)
- **W5** Audit + Observability (ClickHouse, метрики)
- **W8.3** Notification Gateway (Email/Telegram/Slack/Teams/SMS/Express)
- **W9.2** MongoDB (AI Feedback, Workflow State, Express dialogs, Agent Memory)

## ⚠️ ЧАСТИЧНО / НЕЗАВЕРШЁННЫЕ
- **W0.6** удалить класс-обёртку `InMemoryTTLCache`
- **W6** 24 layer violations (БЛОКЕР для тестов)
- **W15.2** иерархия `BaseIntegrationSettings/BaseBotChannelSettings`

## ❌ ПРЕДСТОЯТ

---

# III. ПЛАН WAVE (с краткими подсказками)

## W0 — ФУНДАМЕНТ И DEFAUNT-DEPS [✅ ~90%]

**Подсказка**: фундамент уже стоит. Закрыть только W0.6 (cachetools напрямую без обёртки), верифицировать grep-чеки на удалённые библиотеки.

**Шаги**:
- 0.1 uv ✅ / 0.2 tests ✅ / 0.3 Granian+Uvicorn ✅
- 0.4 fastapi-limiter ✅ / 0.5 native redis Lock ✅
- 0.6 cachetools напрямую ⚠️ — **доделать**: `grep "InMemoryTTLCache" src/ → 0`
- 0.7 prefect удалён ✅ / 0.8 polars в DSL ✅ / 0.9 httpx ✅
- 0.10 langmem+Mongo ✅ / 0.11 один PromptRegistry ✅

**DoD**: `grep -E "(prefect|aiohttp|InMemoryTTLCache)" src/ → 0`

---

## W1 — АРХИТЕКТУРНЫЙ ФУНДАМЕНТ [✅]

**Подсказка**: ABC в `core/interfaces/`, линтер слоёв с allowlist, Redis audit с миграцией snapshot→PG, sessions→Mongo.

**DoD**: `python tools/check_layers.py` → 0 новых нарушений (24 в allowlist для W6).

---

## W2 — ИНФРАСТРУКТУРНЫЙ СЛОЙ [✅]

**Подсказка**: первый набор Gateway (CacheBackend, ObjectStorage, Antivirus, CertStore) с фабриками и переключаемыми бэкендами.

**Шаги**: 2.1 CertStore (Vault/PG/memory) / 2.2 CacheBackend (Redis/KeyDB/Memcached/memory) / 2.3 ObjectStorage (S3/MinIO/LocalFS) / 2.4 Antivirus (ClamAV unix/tcp/HTTP).

---

## W3 — DSL CORE [✅]

**Подсказка**: Pipeline + processors + bidirectional YAML+Python — это ядро. Без него остальные Wave бессмысленны.

**Шаги**: 3.1-3.5 базовые процессоры / 3.6 redirect / 3.7 windowed_dedup + multicast / 3.8 to_yaml/load_pipeline_from_yaml.

---

## W4 — EXPRESS BOTX [✅]

**Подсказка**: ExpressBotClient (BotX HTTP API + JWT HS256) + 7 DSL-процессоров (send/reply/edit/send_file/mention/typing/status).

---

## W5 — АУДИТ И OBSERVABILITY [✅]

**Подсказка**: AuditLog в ClickHouse + расширенные метрики (HTTP/DSL/Cache/Queue/Express/AI/Antivirus).

---

## W6 — УСТРАНЕНИЕ 24 LAYER VIOLATIONS [❌ ПРИОРИТЕТ #1]

**Подсказка**: главный блокер — services/ и entrypoints/ напрямую дёргают infrastructure/. Лечить через DI (Depends/конструктор), не через прямые import. Без этого нельзя писать unit-тесты с моками.

**Шаги**:
- 6.1 Очистить allowlist (4 stale записи)
- 6.2 services/core/ (orders, users, admin, base) — Repository через DI
- 6.3 services/ai/ (agent_memory, ai_agent, llm_judge, semantic_cache, rag) — клиенты через конструктор
- 6.4 services/io/ + services/ops/ + services/notebooks/
- 6.5 entrypoints/ (admin_*, files, express/router, streamlit)

**DoD**: `python tools/check_layers.py → НОВЫЕ нарушения: 0`

---

## W7 — SELF-HEALING + ОПТИМИЗАЦИЯ [плановое расширение]

**Подсказка**: на основе метрик W5 — circuit breaker (purgatory) везде, retry с jitter, SelfHealer service-loop. Использует существующие Gateway (HTTP/DB/MQ).

**DoD**: `kill postgres-primary && curl :8000/api/v1/orders → 200` (через fallback).

---

## W8 — ENTRYPOINTS КОНСОЛИДАЦИЯ

**Подсказка**: Auth через X-Auth-Method header + DSL-процессор `auth`. SOAP/WSDL + XML/XSD вкладки в Schema Viewer. NotificationGateway (8.3 ✅). Реорганизация settings.

**Шаги**: 8.1 auth / 8.2 schema viewer / 8.3 notify ✅ / 8.4 settings.

---

## W9 — MONGODB И ELASTICSEARCH

**Подсказка**: Mongo для flexible schema (notebooks, ai_feedback, workflow_state, express_dialogs, connector_configs, agent_memories). ES для полнотекстового поиска по логам/заказам/документам.

**Шаги**: 9.1 notebook versioning / 9.2 Mongo collections ✅ / 9.3 Elasticsearch.

---

## W10 — CEDRUS И CERT STORE

**Подсказка**: интеграционные тесты CertStore с реальным Vault и PG (юнит уже есть в W2.1). Подключение к Cedrus — отдельный коннектор.

---

## W11 — DSL ПРОЦЕССОРЫ: ПОЛНЫЙ НАБОР

**Подсказка**: матрица всех процессоров (~25 шт). Закрытие пробелов: scan_file, audit, auth, notify, cedrus_query, get_feedback_examples.

**DoD**: `python tools/dsl_coverage.py → 100%`.

---

## W12 — RAG / TENANT / CI-CD

**Подсказка**: RAG ингест (chunking, embeddings, vector store), multi-tenant изоляция, CI/CD pipeline (test+build+lint+docs+deploy).

---

## W13 — ФОНОВЫЕ ЗАДАЧИ (TaskIQ + structured concurrency)

**Подсказка**: TaskIQ для deferred/background/outbox (НЕ для durable workflow и НЕ для cron — оставить APScheduler+DSL Runner). Заменить хаотичные `asyncio.create_task` на `anyio.TaskGroup`. Dask только optional для batch-heavy.

**Шаги**: 13.1 TaskIQ broker / 13.2 DSL defer-process / 13.3 anyio TaskGroup / 13.4 Dask optional.

**Gateway создание**: `ExecutionBackend` объединяет local/TaskIQ/Dask.

---

## W14 — DSL ЭВОЛЮЦИЯ

**Подсказка**: action отделён от transport (один action — много триггеров). Unified batch/stream contract. Late events / watermarks. Side-effect classification (pure/stateful/side_effecting).

**Шаги**: 14.1 ActionRegistry+Dispatcher (Gateway!) / 14.2 batch+stream / 14.3 watermarks / 14.4 side-effects.

**Gateway создание**: `ActionDispatcher` объединяет все бизнес-действия.

---

## W15 — TELEGRAM/EXPRESS HIERARCHY

**Подсказка**: pybotx spike. Иерархия `BaseIntegrationSettings → BaseWebhookChannelSettings → BaseBotChannelSettings`. Express и Telegram реализуют одинаковый контракт.

**Шаги**: 15.1 pybotx ADR / 15.2 hierarchy / 15.3 telegram-ready.

---

## W16 — PLUGINS / TENANT / CI-CD

**Подсказка**: plugin API (entrypoint groups), template плагина, marketplace pattern. Multi-tenant: per-tenant routes, secrets, quotas.

---

## W17 — WIKI И ДОКУМЕНТАЦИЯ (BASE — расширяется в W34)

**Подсказка**: базовая wiki + Express Bot integration guide + DSL Cookbook + Migration Guide. Финальная документация — в W34.

---

## W18 — ТЕСТИРОВАНИЕ (RAMP UP)

**Подсказка**: довести coverage до 70%. Параллельно 4 субагента на разные подсистемы. Добавить perf и chaos.

**Структура**:
```
tests/unit/  tests/integration/  tests/e2e/  tests/perf/  tests/chaos/
```

---

## W19 — RELEASE READINESS / SOAP / GraphQL

**Подсказка**: подготовка релизов — SemVer + git-cliff CHANGELOG + zero-downtime deploy + миграции. Реализация SOAP-эндпоинтов и GraphQL-сервера, если ещё не покрыты.

---

## W20+ — ФИНАЛЬНЫЙ РЕФАКТОРИНГ НАСТРОЕК [последний шаг]

**Подсказка**: запускается **в самом конце**. `tools/config_audit.py` находит зомби-настройки и дубликаты. `config.yml` чистится от orphan-ключей. Settings без alias/yaml-key/description — лечатся. Документ `docs/CONFIG_REFERENCE.md` авто-генерируется.

**Шаги**:
- 20.1 audit `src/core/config/`
- 20.2 audit `config.yml`
- 20.3 иерархия (BaseConnector/BaseSource/BaseSink Settings)
- 20.4 авто-документ CONFIG_REFERENCE.md

**DoD**: `python tools/config_audit.py → 0 zombies, 0 duplicates`.

---

## W21 — DEV-СТЕНД БЕЗ ТЯЖЁЛОЙ ИНФРЫ

**Подсказка**: одна команда `make dev-light` поднимает сервис без Docker за <5 секунд. SQLite вместо PG, cachetools вместо Redis, LocalFS вместо S3, .env+keyring вместо Vault, TinyDB вместо Mongo, SQLite-FTS5 вместо ES. APP_PROFILE=dev_light/dev/staging/prod.

**Шаги**:
- 21.1 APP_PROFILE + config_profiles/
- 21.2 SQLite как полный backend (alembic + JSONB-helpers)
- 21.3 6 параллельных fallback-бэкендов (Audit/DocStore/Search/MQ/Secrets/Metrics)
- 21.4 docs/QUICKSTART.md + полировка конфигов (`.env.example` only-secrets, `vault.enabled` в YAML, Oracle-validator драйверов, удаление 6 dead-полей, расширение AI-провайдеров: OpenRouter/NIM/OpenAI, prod-like `dev.yml` + disk-only `dev_light.yml`)
- **21.5 Settings codegen**: автогенерация Settings-класса + YAML-секции + `.env.example` записей одной командой (см. ниже)

**DoD**: `APP_PROFILE=dev_light uv run python -m app.main` → :8000/health=200, :8501=200, нет Docker.

**Gateway создание**: `SecretsBackend`, `AuditBackend`, `DocStoreBackend`, `SearchBackend`, `MQBackend`, `MetricsBackend`.

---

## W21.5 — SETTINGS CODEGEN (автогенерация конфигурации)

**Подсказка**: добавление новой группы настроек сейчас — три синхронных правки (Settings-класс в `src/core/config/...`, секция в `config_profiles/base.yml`, секреты в `.env.example`). Цель — одна команда генерирует всё атомарно по описанию полей.

**Сценарий использования**:

```bash
# CLI или DSL-описание:
python tools/codegen_settings.py new \
  --name kafka \
  --env-prefix KAFKA_ \
  --field bootstrap_servers:str:"localhost:9092":non-secret \
  --field topic_prefix:str:"gd_":non-secret \
  --field timeout_ms:int:30000:non-secret \
  --field username:str:"":secret \
  --field password:str:"":secret
```

Создаёт атомарно:
1. `src/core/config/services/kafka.py` — `KafkaSettings(BaseSettingsWithLoader)` с указанными `Field`-полями.
2. Регистрация в `src/core/config/settings.py::Settings`.
3. Секция `kafka:` в `config_profiles/base.yml` с non-secret defaults.
4. Записи `KAFKA_USERNAME=`, `KAFKA_PASSWORD=` в `.env.example` (по env_prefix + name).
5. Прогон `python tools/config_audit.py` для подтверждения 0 issues.

**Шаги**:
- 21.5a `tools/codegen_settings.py` — CLI: `new`, `add-field`, `remove`, `--dry-run`. AST-вставка в `settings.py`, YAML round-trip через `ruamel.yaml` (сохранение комментариев), append-секция в `.env.example`.
- 21.5b DSL-альтернатива: YAML-описание (`config-spec/<name>.yml`) → idempotent apply. Полезно для batch-генерации и git review всего описания.
- 21.5c Шаблоны: `BaseSettingsWithLoader`, `BaseConnectorSettings` (с pool/timeout/retry), `BaseBotChannelSettings` (с api_base_url/signature_header).
- 21.5d Reverse-codegen: `tools/codegen_settings.py extract --class KafkaSettings` — из существующего класса генерирует config-spec.yml для воспроизведения.
- 21.5e Интеграция в `make`: `make config-new NAME=kafka` запускает интерактивный wizard.

**Контракт описания поля**:
- `name:type:default:visibility[:constraints]`
- `visibility ∈ {secret, non-secret}` — определяет, идёт ли поле в `.env.example` (как `<ENV_PREFIX><NAME_UPPER>=`) или в `base.yml` с default.
- `constraints` (optional): `ge=N`, `le=N`, `min_length=N`, `max_length=N`, `pattern=...`.

**DoD**:
- `python tools/codegen_settings.py new --name kafka ...` создаёт 4 артефакта; `make config-audit` → 0 issues.
- Reverse-codegen для всех существующих 32 классов идёт round-trip (`extract` → `new` даёт идентичный AST).
- Покрытие тестами: pytest на codegen-выход (структура файла, наличие фикстур YAML/env, валидность через `ast.parse`).

**Зависимости**:
- `ruamel.yaml` (round-trip YAML с комментариями) — добавить в `pyproject.toml` (см. правило про dependency-decision).
- `libcst` для безопасных AST-правок `settings.py` (или ручной AST-template подход).

---

## W22 — ЕДИНАЯ ТОЧКА ЗАПУСКА (Single Invoker)

**Подсказка**: `Invoker` — главный Gateway проекта. Любая функция вызывается через него с режимом sync/async-api/async-queue/deferred/background/streaming. Любой протокол (HTTP/SOAP/gRPC/WS/MQ/Schedule) — через адаптер в Invoker. Reply channels: API/Queue/WS/Email/Express.

**Шаги**:
- 22.1 `core/interfaces/invoker.py` + `services/execution/invoker.py`
- 22.2 Адаптеры протоколов (HTTP/SOAP/gRPC/WS/MQ/Scheduler)
- 22.3 ReplyChannel registry (5 типов)
- 22.4 DSL процессор `invoke`
- 22.5 Streamlit Invocation Console

**DoD**: один action вызывается из 6 протоколов с identicial sync-результатом и identicial invocation_id для async.

**Gateway создание**: `Invoker`.

---

## W23 — УНИВЕРСАЛЬНЫЕ DSL-SOURCES

**Подсказка**: новые интеграции описываются YAML без изменения ядра. 10 типов источников в одном `SourceRegistry` Gateway.

**Шаги**:
- 23.1 Source ABC (`core/interfaces/source.py`)
- 23.2 CDC (PG logical replication через psycopg)
- 23.3 File/Dir Watcher (watchdog)
- 23.4 MQ (Kafka/RabbitMQ/NATS/Redis-Streams)
- 23.5 Webhook (универсальный с HMAC/JWT/mTLS)
- 23.6 SOAP (spyne, WSDL gen)
- 23.7 gRPC (proto gen)
- 23.8 WebSocket
- 23.9 Polling (cron + http + diff)
- 23.10 SourceRegistry + DI

**DoD**: создание интеграции = только YAML + опц. action; ядро не меняется.

**Gateway создание**: `SourceRegistry` + (через симметрию) `SinkRegistry` для исходящих.

---

## W24 — ИМПОРТ POSTMAN/SWAGGER/WSDL [✅ closed 2026-04-30]

**Подсказка**: Postman v2.1 / OpenAPI 3.x / WSDL → автогенерация Connector + DSL external_call sinks + Streamlit-форма вызова. Импорт идемпотентен (не дублирует при повторе).

**Реализовано** (commit `<wave-e>`, ADR-033):
- `core/interfaces/import_gateway.py` — Protocol + `ImportSourceKind`.
- `core/models/connector_spec.py` — `ConnectorSpec` + `EndpointSpec` + `AuthSpec` + `SecretRef`.
- `infrastructure/import_gateway/{postman,openapi,wsdl,factory}.py` — 3 backends + factory.
- `services/integrations/import_service.py` — orchestration: idempotency (SHA256), persist в connector_configs, orphan-cleanup, secret_refs.
- Миграция call-sites (REST `/api/v1/imports/*`, DSL actions `connector.import|list_imported`, Streamlit `26_Import_Schema.py`, `manage.py`).
- Удалены 2 legacy-стэка: `src/tools/schema_importer/` (~620 LOC) + `src/dsl/importers/` (~455 LOC).
- 23 теста (5 postman + 5 openapi + 3 wsdl + 3 factory + 7 service).
- Документация: `docs/reference/import_gateway.md` + ADR-033.

**Шаги** (исходный план): 24.1 Postman ✅ / 24.2 OpenAPI ✅ / 24.3 WSDL ✅ / 24.4 Streamlit Wizard ✅ (минимальный — `26_Import_Schema.py`).

**Gateway создание**: `ImportGateway` ✅.

---

## W25 — LIVE BI-DIRECTIONAL YAML ↔ PYTHON

**Подсказка**: правишь YAML — DSL hot-reload через watchdog. Правишь Python builder в dev — пишет YAML обратно. Версионирование с обратной совместимостью.

**Шаги**: 25.1 yaml_watcher / 25.2 builder hooks / 25.3 versioning + migrations.

---

## W26 — УСТОЙЧИВАЯ ИНФРАСТРУКТУРА

**Подсказка**: circuit breaker (purgatory) для всех внешних. Fallback chains для 11 компонентов (см. таблицу ниже). Health check matrix (live/ready/deep). Миграция всех legacy-роутов на DSL.

**Fallback chains**:
- PG → SQLite read-only
- Redis → Memcached → in-process
- MinIO → LocalFS
- Vault → .env+keyring
- ClickHouse → PG audit table → JSON-файл
- Mongo → PG jsonb table → TinyDB
- ES → SQLite FTS5
- Kafka → Redis Streams → in-memory queue
- ClamAV → HTTP-AV → skip+warn
- SMTP → file-mailer
- Express → Email → Slack

**DoD**: `grep "@router.\(get\|post\)" src/entrypoints/api/v1/endpoints/ → 0` (всё через DSL).

---

## W27 — ВЫСОКАЯ СКОРОСТЬ

**Подсказка**: расширить polars-процессоры (query/join/aggregate/pivot). DuckDB для аналитических запросов в pipeline. orjson/msgspec вместо json (~5-10x). Granian уже на uvloop. Bench-suite (locust + k6).

**Шаги**: 27.1 polars-extended / 27.2 Dask optional (W13.4) / 27.3 DuckDB / 27.4 orjson / 27.5 server tuning / 27.6 perf-suite.

---

## W28 — RPA UNIVERSAL (полный стек, ~120 процессоров)

**Подсказка**: главный Wave для гибридной природы проекта. Сервис интегрируется с **чем угодно** — даже без API. Все RPA-процессоры наследуют `RPAProcessor` ABC, используют `ResourceManager` (пулы), Sandbox, Evidence Store. Каждая операция описывается YAML.

**Структура (20 шагов)**:
- **28.0** Foundation: ABC + ResourceManager + Sandbox (subprocess/container/vm) + Evidence Store + Recorder framework
- **28.1** Browser: Playwright + Patchright (anti-detect) + Selenium fallback + CAPTCHA solvers + proxy ротация + fingerprint + network intercept + scraping + DevTools CDP + recorder
- **28.2** Desktop: pyautogui + pywinauto (Windows) + AppleScript + Linux + image-match + recorder
- **28.3** OCR/CV: Tesseract/EasyOCR/PaddleOCR + Document Understanding + image processing + barcode/QR
- **28.4** Filesystem: bulk + archives (7z/rar/zip) + hash + format conversion (LibreOffice/Pandoc) + encryption (PGP/AES) + signing
- **28.5** Documents: Word/Excel/PowerPoint/PDF (read+write+merge+sign+forms) + HTML/MD/LaTeX + MJML
- **28.6** Network: SSH/SFTP/FTP/SMB/WebDAV/Telnet/DNS/LDAP/AD/MQTT/AMQP/Kafka producer
- **28.7** Email: IMAP/POP3/Exchange OAuth2/Gmail API
- **28.8** External Database: SQL via ODBC + MSSQL/Oracle + Mongo/Cassandra/Influx/Snowflake/BigQuery/Neo4j + DataLake (parquet/iceberg)
- **28.9** Cloud: AWS/Azure/GCP/Yandex
- **28.10** ERP/CRM: 1С (OData/HTTP/COM) / SAP (RFC/GUI) / Salesforce / HubSpot / Bitrix24 / amoCRM / Jira / Confluence / SNOW / СМЭВ
- **28.11** Chat: Discord/Mattermost/RocketChat/VK/WhatsApp Business
- **28.12** Hardware: Modbus / OPC-UA / Serial RS-232/485
- **28.13** Voice: TTS (Edge/gTTS/SpeechKit) / STT (Whisper) / audio processing
- **28.14** HITL: Approval Gate (durable pause + multi-channel) + Manual Form Entry
- **28.15** Script execution: subprocess/container/Jupyter (papermill) с rlimit/Docker sandbox
- **28.16** Patterns: reusable `dsl_rpa_blocks/` + foreach/switch + Saga/compensations + Retry с recreate + parallel
- **28.17** Pool: Browser pool / License-limit semaphores / Schedule / durable background
- **28.18** Recording: Browser (Playwright codegen) + Desktop (pynput) + Replay + HAR-based
- **28.19** Streamlit Console: Tasks / Evidence / Recorder / Library / Pool Monitor (5 страниц)
- **28.20** Security: audit per step / secret masking in evidence / permission model / GDPR-152ФЗ

**Gateway создание**: `ResourceManager`, `RPABrowserBackend` (Playwright/Patchright/Selenium), `RPADocBackend` (read/write через 6 библиотек).

**Опциональные группы зависимостей** в pyproject.toml: `rpa-browser`, `rpa-desktop`, `rpa-ocr`, `rpa-cv`, `rpa-docs`, `rpa-network`, `rpa-email`, `rpa-db-extra`, `rpa-cloud`, `rpa-erp`, `rpa-chat`, `rpa-hardware`, `rpa-voice`, `rpa-captcha`, `rpa-sandbox`, `rpa-archive`.

**DoD**: 100+ RPA kind-ов в YAML; `python tools/dsl_coverage.py --section rpa` → 100%; sandbox-тесты блокируют fork-bomb / memory-leak / network-egress.

---

## W29 — РАСШИРЕНИЕ AI

**Подсказка**: единый ToolsRegistry для агентов (REST/DSL/RPA/DB tools). MCP-сервер для подключения внешних AI (Claude Desktop, Cline). Аналитический агент (polars/duckdb tools). Поисковый агент (RAG).

**Шаги**: 29.1 ToolsRegistry / 29.2 MCP server / 29.3 analytics agent / 29.4 search agent.

**Gateway создание**: `LLMBackend` (если ещё не) объединяет OpenAI/Anthropic/local + MCP.

---

## W30 — STREAMLIT REORGANIZATION

**Подсказка**: 30 плоских страниц → 6 групп. Унифицированный dashboard framework. S3 Browser. Log Viewer (фильтры trace_id/route_id/level). Theming + auth.

**Группы**:
- 🏠 Home
- 📊 Dashboards (System / DSL / Integrations / AI)
- ⚙️ Operations (Invocation Console / DSL Editor / RPA Console / Notebooks / Express)
- 🛠 Admin (Routes / Connectors / Schedules / Users / Cert / Settings)
- 🔍 Observability (Logs / Audit / Metrics / Traces)
- 💾 Data (S3 Browser / DB / Search / Schema)
- 🤖 AI (Prompts / RAG / Feedback / Memory)

---

## W31 — АУДИТ И ЗАМЕНА БИБЛИОТЕК

**Подсказка**: pip-deptree + unimport + vulture + deptry. Кандидаты на замену: pydantic v1→v2, requests→httpx (если остался), motor→pymongo[asyncio] 4.9+, aiohttp→httpx (verify W0.9), structlog→loguru (один logger), dateutil→whenever, marshmallow→pydantic v2.

**DoD**: `uv run deptry src/ → 0`.

---

## W32 — ДЕДУПЛИКАЦИЯ + GATEWAY-ENFORCEMENT

**Подсказка**: Generic Repository<T,ID>. Единая иерархия исключений `AppError → DomainError/InfraError/AuthError`. Единый response envelope `{data, error, meta:{trace_id, ts}}`. Audit-операции — только через `AuditService.record()`.

**Дополнительно по Правилу 13.5**: проверить все Gateway: `python tools/check_gateways.py → 0 orphan backends, 0 дубликатов методов`. Объединить найденные «бывшие дубликаты» в существующие Gateway.

---

## W33 — РЕОРГАНИЗАЦИЯ ДИРЕКТОРИЙ + DEAD CODE

**Подсказка**: финальная структура (см. ниже). Удалить мёртвый код (`vulture --min-confidence 80`). Удалить неиспользуемые зависимости (`deptry`). SBOM (CycloneDX).

**Целевая структура** (упрощённо):
```
src/
├── core/{config,interfaces,exceptions,decorators,utils,types}
├── infrastructure/{db,cache,storage,secrets,docstore,search,audit,
│                   queue,messaging,sources,sinks,notifications,
│                   antivirus,security,repositories,clients,observability}
├── services/{core,ai,execution,actions,import,notebooks,io,ops,rpa}
├── dsl/{engine,orchestration,sync,yaml_store,versioning}
├── entrypoints/{api,soap,grpc,ws,express,webhook,mq,scheduler,
│                streamlit_app,middlewares}
├── plugins/
└── main.py

tests/{unit,integration,e2e,perf,chaos}
config_profiles/{dev_light,dev,staging,prod}.yml
dsl_routes/*.yml
dsl_rpa_blocks/*.yml
docs/...
```

**DoD**: `tools/check_layers.py` + `vulture` + `deptry` + `tools/check_gateways.py` — все green.

---

## W34 — ДОКУМЕНТАЦИЯ (Sphinx + README + Wiki + Runbooks)

**Подсказка**: Docs as Code. Sphinx + Furo + MyST. Авто-генерация API/DSL/Config reference из docstrings. Streamlit Wiki как первый рубеж (рендерит .md из docs/, поиск через whoosh, live examples). 9-15 tutorials по фреймворку Diátaxis. 10+ runbook'ов. 13+ ADR. CI/CD docs (GH Actions + ReadTheDocs + multiversion). Vale prose linter.

**Шаги**:
- 34.1 Sphinx foundation
- 34.2 Auto-gen (API/DSL/Config/Glossary)
- 34.3 9-15 tutorials
- 34.4 10+ runbook'ов
- 34.5 Streamlit Wiki (9 страниц + поиск + live examples)
- 34.6 README актуализация + CONTRIBUTING + CHANGELOG (git-cliff)
- 34.7 CI/CD docs
- 34.8 Vale + docs_coverage
- 34.9 i18n (опц.)

**DoD**: `make docs` → 0 warnings; `python tools/docs_coverage.py` → ≥95%; ≥10 runbook'ов; ≥13 ADR.

---

# IV. ROADMAP (СПРИНТЫ)

| Спринт | Длит. | Wave | Содержание |
|---|---|---|---|
| 1 | 2 нед | W6 + W0.6 + W21.1-21.2 | Разблокировка тестов + dev_light базовый |
| 2 | 2 нед | W14.1 + W22 | Action Dispatcher + Single Invoker |
| 3 | 3 нед | W23 + W24 + W25 | Sources + Import + Live YAML |
| 4 | 4 нед | **W28** | RPA Universal (расширенный) |
| 5 | 2 нед | W29 + W26 | AI ext + Stable infra + миграция роутов на DSL |
| 6 | 2 нед | W27 + W30 | Скорость + Streamlit reorg |
| 7 | 1 нед | W31 + W32 | Audit библиотек + дедупликация |
| 8 | 1 нед | W34 | Документация |
| 9 | 1 нед | W20+ + W33 | Финал config + reorg директорий + dead code |

**Итого**: ~18 недель / **4.5 месяца**.

---

# V. DEFINITION OF DONE (К ПРОДУ)

```bash
# 1. Тесты ≥70%
uv run pytest tests/ -v --cov=src --cov-report=term-missing

# 2. Чистота кода
python tools/check_layers.py            # 0
python tools/check_gateways.py          # 0 orphan
python tools/config_audit.py            # 0 zombies
uv run mypy src/ --strict               # 0
uv run ruff check src/                  # 0
uv run vulture src/ --min-confidence 80 # 0
uv run deptry src/                      # 0

# 3. Dev light без Docker
APP_PROFILE=dev_light uv run python -m app.main &
sleep 3 && curl :8000/health/live :8501  # → 200, 200

# 4. Все протоколы → один action
curl :8000/api/v1/invocations           # REST
curl :8000/soap/...                     # SOAP
grpcurl :8001 ...                       # gRPC
wscat :8000/ws/invocations              # WS
redis-cli XADD invocations.* ...        # MQ

# 5. DSL покрывает все интеграции
python tools/dsl_coverage.py            # API/SOAP/gRPC/WS/Webhook/Watcher/CDC/MQ/RPA — 100%

# 6. Fallback работает
docker stop postgres && curl :8000/api/v1/orders  # → 200 через SQLite

# 7. Performance
k6 run tests/perf/k6_script.js          # p95 < 200ms, RPS > 1000

# 8. Документация
make docs                               # 0 warnings
python tools/docs_coverage.py           # ≥95%

# 9. Все Wave закрыты
grep "❌" MASTER_PROMPT_V9.md           # 0
```

---

# VI. РИТУАЛ ОБСУЖДЕНИЯ ПЕРЕД WAVE (Правило 8)

```
[главный агент]: Запуск ритуала Wave N.

[субагент-А СД] Архитектура:
  - Что меняется в контрактах/ABC
  - Альтернативы (2-3)
  - Влияние на существующие Gateway
  - Риск layer policy

[субагент-Б АН] Use-cases:
  - 3-5 сценариев для проверки
  - Что НЕ покрыто планом
  - Приоритезация под бизнес

[субагент-В ДО] Инфра:
  - Новые зависимости (минимизировать!)
  - docker-compose / env / vault изменения
  - CI/CD влияние

[субагент-Г ТЕС] Тесты:
  - Unit / integration / e2e / perf
  - Можно ли в dev_light?
  - Chaos-тесты для fallback

[главный агент] → ОТЧЁТ ЗАКАЗЧИКУ:
  1. Согласованный план шагов
  2. Расхождения между агентами (если есть)
  3. ПРОВЕРКА Правила 13:
     - есть ли логически близкие функции? → Gateway?
     - не оверинжиниринг ли это?
  4. 2-3 ДОПОЛНИТЕЛЬНЫХ предложения
  5. Известные риски

ОЖИДАТЬ "ОК" ЗАКАЗЧИКА. Только после — РАЗ начинает кодить.
```

---

# VII. КЛЮЧЕВЫЕ МЕТРИКИ

| Метрика | Цель |
|---|---|
| Python файлов | стабилизация ~700 |
| Тест-файлов | ≥100 (W18) |
| Coverage | ≥70% |
| Layer violations | 0 |
| Gateway orphans | 0 |
| Config zombies | 0 |
| TODO/FIXME | ≤5 |
| DSL kind-ов | 150+ (включая RPA) |
| Streamlit разделов | 6 групп / ~40 страниц |
| Fallback chains | 11 |
| Auth methods | 7+ |
| Cert backends | 3 |
| Cache backends | 4 |
| Storage backends | 2 |
| Antivirus backends | 3 |
| RPA процессоров | 100+ |
| ADR | ≥13 |
| Runbooks | ≥10 |
| Tutorials | ≥9 |
| Sphinx warnings | 0 |
| Запуск dev_light | <5 сек, без Docker |
| p95 latency | <200ms |
| RPS sustained | >1000 |

---

# VIII. ФИНАЛЬНАЯ СВОДКА V9

| Параметр | Значение |
|---|---|
| Всего Wave | 35 (W0–W34) |
| Закрыто | ~12 (W0-5, W8.3, W9.2 частично) |
| Предстоит | ~23 |
| Шагов всего | ~160 |
| Спринтов | 9 |
| Длительность | 4.5 месяца |
| Ключевых Gateway | 21 |
| Новых правил против v8 | Правило 13 (anti-overengineering + Gateway) |

---

# IX. НАПОМИНАНИЕ ПЕРЕД ЛЮБЫМ ШАГОМ

```bash
# 1. Стандартная инициализация (Правило 0)
graphify update . && graphify query <модули>
cat .claude/DECISIONS.md .claude/REDIS_AUDIT.md

# 2. Anti-overengineering check (Правило 13.1)
# - Можно меньшим кодом? Все слои нужны? Не дублирую? Нет «магии»?

# 3. Gateway check (Правило 13.2-13.4)
# - Объединяю 2+ похожие функции? → Gateway proposal заказчику!
# - Создаю backend? → ему уже есть Gateway?

# 4. Pre-Wave ritual (Правило 8) — для глобальных Wave
# 4 субагента → отчёт → ОК заказчика

# 5. Только потом — кодинг

# 6. После шага — коммит + graphify update
git commit -m "wave{N}.{M}: ..."
graphify update .
```

**Формат вывода каждого шага**:
```
[СД] Архитектурное решение: ...
[АН] Use-cases: ...
[РАЗ] Реализовано: ...
[ДО] Конфигурация: ...
[ТЕС] Результат: PASSED (N/N)
git commit: "wave{N}.{M}: ..."
```

---

*v9 — единая операционная версия. Хранить в корне репо как `MASTER_PROMPT.md` (без версии в имени для удобства).*
*Подробности по каждому Wave — в `MASTER_PROMPT_V8.md` и `MASTER_PROMPT_V8_AMENDMENT.md` как референс.*