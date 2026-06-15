# Master Prompt: Агент-разработчик gd_integration_tools

> Версия: v4-factcheck
> Проект: gd_integration_tools — domain-agnostic интеграционная шина (Python 3.14+, Apache-Camel/Airflow-style).
> База: фактчекинг 4 итераций анализа по реальным файлам репозитория.

## 1. Философия проекта

- **Ядро domain-agnostic, бизнес-логика только в `extensions/<name>/`**.
- **80% декларативно (DSL YAML/Python) / 20% Python** через `call_function('module:fn')`.
- **Capability-checked фасады**: плагины импортируют только `gd_integration_tools.core.*` и проверенные фасады. Прямой импорт из `infrastructure/*` / `services/*` запрещён.
- **Async-first**: FastAPI/Temporal, никакого blocking I/O в async-контексте.
- **Pydantic для DTO/схем**, type hints везде (Python 3.14+ синтаксис).
- **Zero Broken Windows**: не оставлять tech debt, не копировать костыли, не добавлять дублирующие библиотеки.
- **Zero Regression**: любое изменение должно покрываться тестами; pre-existing баги фиксятся или явно документируются.
- **Facade-first**: если пользователь должен выбирать бэкенд — нужен фасад, который скрывает выбор.

## 2. Ключевые коррекции после фактчекинга

Несколько утверждений из предыдущих анализов оказались устаревшими или неточными. Используй эти факты как baseline:

| Утверждение | Статус | Факт |
|-------------|--------|------|
| HITL не реализован | CORRECTED | HITL реализован: `hitl_service.py`, `hitl_approval.py`, REST `/hitl`, UI `72_HITL_Panel.py`. Процессор ждёт решение через polling, сервис шлёт Temporal signal. |
| Prompt caching (Anthropic) не реализован | CORRECTED | Реализовано в `infrastructure/ai/prompt_cache_middleware.py`, интеграция в `llm_mixin.py`. |
| RAG DSL `rag_query()`/`rag_ingest()` отсутствуют | CORRECTED | Есть в `dsl/builders/ai_rpa/ai_llm.py` и процессорах `rag/query.py`, `rag/ingest.py`. |
| S3 multipart upload отсутствует | CORRECTED | Реализован `put_object_multipart()` в `infrastructure/clients/storage/s3_pool/client.py`. |
| S3→LocalFS fallback только при init | CORRECTED | Runtime fallback через `FallbackObjectStorage` работает для любых ошибок primary. |
| Debezium — scaffold без Kafka consumer | CORRECTED | Полноценный `AIOKafkaConsumer` loop в `infrastructure/cdc/debezium_events_backend.py`. |
| gRPC file streaming отсутствует | CORRECTED | `files.proto` содержит `DownloadFile`/`UploadFile` с chunked streaming. |
| DSL Variables (Airflow-style) отсутствуют | CORRECTED | `DSLVariableStore` с бэкендами Consul/Postgres/InMemory и `${var('...')}` в `core/dsl/variables.py`. |
| CertStore не поддерживает Consul | CORRECTED | Backend `"consul"` реализован в `infrastructure/security/cert_store/backend_consul.py`. |
| mem0ai не подключён | PARTIAL | Адаптер `Mem0MemoryAdapter` есть, но SDK удалён из зависимостей и feature-flag default-OFF. |
| 61 Settings-класс | CORRECTED | В `core/config` 71 класс `*Settings`, плюс 24 `*Flags` (итого 96 конфигурационных классов). |
| 1641 функция без docstring | CORRECTED | 1601 публичная функция `src/backend` без docstring; все функции — ~3531 без docstring. |

## 3. Матрица фасадов

| Домен | Статус | Файлы / примечания |
|-------|--------|---------------------|
| AI Gateway | OK | `services/ai/gateway/client.py` — LiteLLM facade |
| Audit | OK | `services/audit/facade.py` |
| Notifications | OK | `services/notifications/facade.py` |
| HTTP | OK | `infrastructure/clients/transport/http_upstream.py` |
| Cache | PARTIAL | Есть `FallbackCache`, `@cached`, но нет единого `CacheFacade` с backend-agnostic API |
| Storage | GAP | `ObjectStorage` interface + `FallbackObjectStorage`, но нет `StorageFacade` для extensions |
| External DB | GAP | Нет `ExternalDatabaseFacade`; extensions используют registry/accessors напрямую |
| Event Bus | GAP | `EventBusMixin` пишет только в properties, backend wiring — carryover |
| Codec | GAP | Нет `CodecFacade`; конвертеры/парсеры разбросаны |
| Auth | PARTIAL | `AuthorizationGateway` есть, но `AuthFacade` для extensions не выделен |
| Secrets | PARTIAL | Vault + CertStore, но нет unified `SecretsFacade` |

**Правило**: если добавляешь новый бэкенд (например, хранилище файлов или кэш), сначала проверь, есть ли фасад. Если нет — создай или расширь существующий. Не добавляй прямых импортов бэкенда в extensions.

## 4. Backlog: P0–P3

### P0 — критично, блокирует production

1. **EventBus DSL backend wiring**
   - `src/backend/dsl/builders/eventbus_mixin.py`
   - Сейчас `EventBusPublishProcessor` только пишет в `exchange.properties`.
   - Действие: подключить реальный `EventBusFacade.publish()` / `subscribe()` при `eventbus_dsl_enabled=True`.

2. **HITL: заменить polling на Temporal signal wait**
   - `src/backend/dsl/engine/processors/hitl_approval.py`
   - Процессор должен ждать `workflow.wait_signal("hitl_approve")` вместо polling.

3. **Agent isolation: LangGraph workflow в sandbox**
   - `src/backend/dsl/engine/processors/agent_dsl/agent_graph.py`
   - Сейчас выполняется в main process. Исследовать запуск в E2B/песочнице или отдельном worker с ограниченными capabilities.

### P1 — высокий приоритет

4. **StorageFacade для extensions**
   - Скрыть S3/MinIO/LocalFS выбор за единым фасадом.

5. **UnifiedCacheFacade**
   - Redis ↔ memory ↔ disk fallback через единый API.

6. **ExternalDatabaseFacade**
   - Унифицировать доступ к PG/Oracle/MSSQL/MySQL/DB2/ClickHouse/Mongo для extensions.

7. **ToS3Processor streaming**
   - `src/backend/dsl/engine/processors/storage/s3.py`
   - Заменить буферизацию `bytes(data)` целиком на multipart streaming upload.

8. **FileWatcher DSL improvements**
   - `src/backend/dsl/builders/sources_mixin/file_sources_mixin.py`
   - Добавить glob-фильтры, batching событий, несколько путей.

9. **Middleware DSL builder**
   - Добавить `.middleware(...)` метод в `RouteBuilder`.

10. **IP restriction: hot-reload + per-route DSL**
    - `src/backend/entrypoints/middlewares/admin_ip.py`
    - Добавить reload через Consul/API и DSL-конфигурацию per-route.

### P2 — средний приоритет

11. **Circuit Breaker consolidation**
    - 8+ реализаций. Оставить одну на `purgatory`, остальные deprecated.

12. **Rate Limiter consolidation**
    - 6+ реализаций. Рассмотреть `limits` как единый backend.

13. **FallbackCache periodic re-probe**
    - `src/backend/core/utils/redis_fallback.py`
    - Добавить фоновую задачу периодического re-probe Redis.

14. **ConsulConfigStore в BaseSettingsWithLoader**
    - `src/backend/core/config/config_loader.py`
    - Добавить Consul как источник настроек.

15. **Settings consolidation**
    - 71 Settings-класс, 63 дублирующихся имени полей. Вынести общие mixin (API connection, DB pool, circuit breaker, retry).

### P3 — низкий приоритет / tech-debt

16. **Docstring coverage**
    - 1601 публичная функция без docstring. Цель: 100% public API.

17. **Frontend consolidation**
    - Два фронтенда (React Admin + Streamlit). Удалить/заморозить admin-react.

18. **mem0ai re-enable**
    - Вернуть `mem0ai` в extra `[ai-memory]` или удалить dead adapter.

## 5. Рекомендуемые библиотеки

### Core (можно добавить сейчас)

| Библиотека | Назначение | Куда |
|------------|-----------|------|
| `dishka` | Async-first DI с scopes | Замена/обёртка `svcs` для async factories |
| `limits` | Единый rate limiter | Consolidate 6+ rate limiter реализаций |
| `instructor` | Structured LLM output | AI processors, tool calling |
| `guardrails-ai` | Структурированная AI-валидация | `guardrails_apply` processor |
| `filetype` | Определение MIME без magic | File processing DSL |
| `fsspec` | Unified filesystem interface | StorageFacade backend |

### Optional / future

| Библиотека | Назначение | Условие |
|------------|-----------|---------|
| `mem0ai` | Long-term memory | Вернуть когда будет Python 3.14 support |
| `langgraph-checkpoint-postgres` | Postgres persistence для LangGraph | Если откажемся от кастомного PostgresSaver |
| `e2b-code-interpreter` | Изоляция агентских workflow | Agent isolation P0 |
| `tenacity` | Единый retry DSL | Замена кастомных retry-циклов |
| `structlog` extensions | Correlation ID, JSON logging | Уже используется, расширить middleware |

## 6. Процесс разработки

### 6.1. Перед задачей — планирование

1. Прочитать `AGENTS.md` и `CLAUDE.md`.
2. Определить, какой домен затронут.
3. Проверить facade-matrix (раздел 3). Если нужен новый фасад — спланировать его.
4. Оценить влияние на extensions (никаких прямых импортов из infrastructure/services).
5. Написать краткий план в свободной форме и согласовать с пользователем, если задача нетривиальная.

### 6.2. Во время задачи

- Type hints everywhere, async-first.
- Pydantic модели для входных/выходных контрактов.
- Capability-gate для cross-layer доступа.
- DSL-first: если функционал может быть декларативным, сделай его DSL-процессором и builder-методом.
- Не добавляй дублирующие библиотеки. Перед добавлением проверь `pyproject.toml`.
- Не оставляй `TODO` без issue/комментария с контекстом.

### 6.3. Self-review checklist после каждой задачи

- [ ] Код проходит `make format`.
- [ ] `make lint` не добавляет новых ошибок в затронутые файлы.
- [ ] `mypy` на изменённых файлах не даёт новых ошибок (pre-existing можно оставить, но задокументировать).
- [ ] Написаны/обновлены unit-тесты для изменённого функционала.
- [ ] Все новые public функции/классы имеют docstring.
- [ ] Проверено влияние на extensions (нет прямых импортов infrastructure/services).
- [ ] Проверено влияние на facade-matrix.
- [ ] Нет hardcoded secrets, PII, токенов.

### 6.4. Zero Regression Policy

- Любое изменение должно либо проходить существующие тесты, либо тесты должны быть обновлены осознанно.
- Pre-existing failures разрешены, но должны быть явно перечислены в комментарии к коммиту.
- Если pre-existing баг мешает вашей задаче — фиксить в том же спринте, не откладывать.

### 6.5. Zero Tech Debt Policy

- Не копировать существующие костыли.
- Не оставлять временные решений без плана удаления.
- При рефакторинге обновлять все call sites.
- Старые реализации (например, duplicate circuit breakers) помечать `@deprecated` и мигрировать постепенно.

### 6.6. Sprint Retrospective

После каждого спринта:
1. Перечислить, что было сделано.
2. Перечислить pre-existing баги, затронутые в спринте.
3. Перечислить tech debt, который не удалось закрыть (с обоснованием).
4. Обновить `CHANGELOG.md` и `PLAN.md` если требуется.
5. Обновить `.claude/KNOWN_ISSUES.md` если нашёл новый systemic issue.

## 7. Архитектурные правила

### 7.1. Слои

```
extensions/<name>/          → business logic only
src/backend/dsl/            → DSL builders, processors, engine
src/backend/core/           → contracts, interfaces, DI, tenancy, auth, AI policy
src/backend/services/       → domain services (facades)
src/backend/infrastructure/ → db, cache, storage, messaging, audit, sources, sinks
src/backend/entrypoints/    → REST/SOAP/gRPC/GraphQL/WS/SSE/MQTT/MCP/CDC
src/frontend/               → Streamlit (primary), admin-react (deprecated)
```

### 7.2. Запрещено

- Импорт `extensions/*` → `infrastructure/*` / `services/*` напрямую.
- Бизнес-логика вне `extensions/<name>/`.
- Secrets в коде, логах, коммитах.
- PII в логах.
- Blocking I/O в async-контексте.
- Изменения в lock-файлах без согласования.
- Force-push, reset --hard.

### 7.3. Обязательно

- `BaseModel` / Pydantic для DTO.
- `pytest` с markers (`unit`, `integration`, `asyncio`, `property`).
- `make lint && make type-check && make test` перед коммитом (с учётом pre-existing failures).
- Conventional commits на русском: `feat:`, `fix:`, `chore:`, `docs:`, `refactor:`, `test:`, `perf:`.
- Атомарные коммиты.

## 8. DSL правила

### 8.1. Processor

```python
from __future__ import annotations
from typing import Any, ClassVar
from src.backend.dsl.engine.context import ExecutionContext
from src.backend.dsl.engine.exchange import Exchange
from src.backend.dsl.engine.processors.base import BaseProcessor

class MyProcessor(BaseProcessor):
    side_effect: ClassVar[Any] = "READ"  # или "WRITE"
    compensatable: ClassVar[bool] = True

    def __init__(self, *, param: str, name: str | None = None) -> None:
        super().__init__(name=name or f"my({param})")
        self._param = param

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        ...

    def to_spec(self) -> dict[str, Any] | None:
        return {"my": {"param": self._param}}
```

### 8.2. Builder mixin

```python
from src.backend.dsl.builders.base import BaseRouteBuilder

class MyMixin:
    def my_step(self: BaseRouteBuilder, param: str) -> BaseRouteBuilder:
        return self._append(MyProcessor(param=param))
```

### 8.3. Обязательно для нового DSL

- Processor + builder mixin.
- Unit-тесты processor и builder-метода.
- Feature-flag в `core/config/features/` (default OFF для экспериментальных фич).
- Docstring с примером YAML DSL.

## 9. Тестирование

- Unit-тесты для processor: `tests/unit/dsl/engine/processors/test_<name>.py`.
- Unit-тесты для builder: `tests/unit/dsl/builders/test_<name>.py`.
- Integration-тесты для фасадов: `tests/integration/<domain>/`.
- Property-based тесты для инвариантов: `tests/property/`.
- Smoke-тесты для plugin lifecycle: `tests/smoke/`.

## 10. Документация

- Каждая public функция/класс — docstring (Google-style или NumPy-style, как в проекте).
- DSL-процессоры — docstring с примерами YAML и Python DSL.
- ADR для архитектурных решений: `docs/adr/`.
- Cookbooks для типовых сценариев: `docs/cookbooks/`.
- Tutorials для onboarding: `docs/tutorials/`.
- После изменения API обновить `docs/api/` (autoapi) и `CHANGELOG.md`.

## 11. Проверка перед коммитом

```bash
make format
make lint
make type-check
uv run pytest tests/unit/<relevant> -q
```

Если `make lint` / `make type-check` падают на pre-existing ошибках — убедись, что твои изменения не добавили новых ошибок в затронутые файлы.

---

## 12. Памятка: что НЕ делать

- Не пиши бизнес-логику в ядре.
- Не добавляй библиотеку, которая дублирует существующую.
- Не оставляй `print()` / `breakpoint()` / `console.log()`.
- Не коммить `.env`, secrets, lock-файлы без согласования.
- Не создавай новый Circuit Breaker / Rate Limiter — используй `purgatory` / `limits`.
- Не создавай новый DI-контейнер — используй `svcs` или планируй миграцию на `dishka`.
