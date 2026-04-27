# ADR-022 — Connector SPI + ConnectorRegistry

- **Статус:** Accepted
- **Дата:** 2026-04-21
- **Фаза:** IL1 (Infrastructure Layer P0)
- **Связанные ADR:** ADR-002 (svcs DI), ADR-005 (tenacity retry), ADR-009 (httpx)
- **Авторы:** claude

## Контекст

К моменту закрытия initial 40/40 фаз инфраструктурный слой фрагментарен:
каждый клиент (Postgres / Redis / Mongo / Kafka / RabbitMQ / SMTP / IMAP / S3 /
httpx / gRPC / SOAP) имеет свой собственный lifecycle (`start`/`stop`/`health`
с разными сигнатурами), свой способ регистрации в svcs, свой набор pool-
параметров в Settings с разными именами полей, и свой (не)набор
observability-метрик. Grep-ом по `src/infrastructure/clients/` видно ≥12
различных `close()`/`stop()`/`disconnect()`/`shutdown()` патернов.

Коммерческие ESB (MuleSoft Connection Provider, Apache Camel Component
interface, WSO2 Carbon Connector SPI, TIBCO BW Adapter interface) решают эту
проблему через единый **Connector SPI** — интерфейс, которому подчиняется
каждый коннектор. Это даёт:

1. Один lifecycle (start/stop/health/validate/reload).
2. Один `ConnectorRegistry` как единая точка bootstrap/shutdown всего слоя.
3. Единый канал Prometheus/OTEL-инструментации (через mixin/base).
4. Возможность централизованно делать `reload(name)` без перезапуска приложения
   (Admin API, Vault rotation, config hot-reload).

## Решение

### Connector SPI

Вводится абстрактный класс `InfrastructureClient` в
`src/infrastructure/clients/base_connector.py`:

```python
class InfrastructureClient(ABC):
    name: str                          # уникальное имя для регистрации.
    pooling: PoolingProfile            # pool-параметры (см. src/core/config/pooling.py).

    @abstractmethod
    async def start(self) -> None: ...
    @abstractmethod
    async def stop(self) -> None: ...
    @abstractmethod
    async def health(self, mode: Literal["fast", "deep"] = "fast") -> HealthResult: ...

    async def validate(self) -> None:    # вызывается периодически scheduler'ом.
        await self.health(mode="fast")

    async def reload(self) -> None:      # drain → rebuild → swap → close old.
        await self.stop()
        await self.start()
```

`HealthResult` — dataclass:

```python
@dataclass
class HealthResult:
    status: Literal["ok", "degraded", "failed"]
    latency_ms: float
    mode: Literal["fast", "deep"]
    details: dict[str, Any] | None = None
    error: str | None = None
```

### ConnectorRegistry

`src/infrastructure/registry.py` — process-wide singleton:

```python
class ConnectorRegistry:
    def register(self, client: InfrastructureClient, *, vault_path: str | None = None) -> None: ...
    def get(self, name: str) -> InfrastructureClient: ...
    async def start_all(self) -> None: ...
    async def stop_all(self) -> None: ...            # reverse order.
    async def health_all(self, mode="fast") -> dict[str, HealthResult]: ...
    async def reload(self, name: str) -> None: ...   # atomic.
    def names(self) -> list[str]: ...
```

Подключается в `src/infrastructure/application/lifecycle.py`:

```python
async def startup():
    registry = ConnectorRegistry.instance()
    register_all_clients(registry, settings)    # декларативная регистрация.
    await registry.start_all()

async def shutdown():
    await ConnectorRegistry.instance().stop_all()
```

### Миграция существующих клиентов

Миграция поэтапная (не big-bang):

1. В IL1 добавляются ABC + Registry + несколько клиентов-пионеров (Redis, Postgres).
2. В IL2 мигрируются Kafka / RabbitMQ / IMAP / HTTP (вместе с профилями upstream).
3. В IL3 добавляется tenant-aware per-tenant sub-registry.

До полной миграции существующие `from src.infrastructure.clients.* import X`
продолжают работать через re-export shim (`DeprecationWarning` — plan deletion
в H3_PLUS).

## Альтернативы

### Альтернатива A — оставить как есть

Обоснование отказа: каждая новая фича (hot-reload, deep health, admin reload,
tenant pools) требует касания 12+ файлов. Масштабируется плохо.

### Альтернатива B — dependency-injector / punq вместо svcs

Обоснование отказа: ADR-002 фиксирует svcs. Новый DI-фреймворк — другой слой.
ABC + Registry — это контракт lifecycle, который **дополняет** svcs (svcs
использует Registry как factory).

### Альтернатива C — использовать готовый framework типа `starlette-admin` или
`fastapi-utils` для lifecycle

Обоснование отказа: их модели заточены под FastAPI-routing, не под
infrastructure connectors. Нет унифицированного health/reload.

## Последствия

### Положительные

- Единый lifecycle → проще shutdown/startup ordering (reverse stop).
- Admin API `POST /admin/connectors/{name}/reload` — тривиально реализуем.
- Health aggregator получает fast/deep режимы автоматически.
- Client metrics (RED) внедряются через Mixin один раз — не 12.
- Тест-coverage можно будет добавить централизованно (когда политика изменится).

### Отрицательные / Риски

- Deprecation shim требует cleanup в H3_PLUS (+1 позиция в списке).
- Неправильный shutdown order может привести к utmp/connection leaks — mitigate:
  `stop_all()` идёт в reverse register order + per-client graceful timeout.
- Подписка на Vault rotation требует знания `vault_path` per client — не все
  клиенты его имеют (обозначен опциональным).

## Коммерческие референсы

- **MuleSoft 4.x Connection Provider** — interface `ConnectionProvider<T>` с
  методами `connect()`, `disconnect()`, `validate()`.
- **Apache Camel Component** — `CamelContext.addComponent()` + `Endpoint.start()`
  / `stop()` lifecycle.
- **WSO2 Carbon Connector** — `AbstractConnector` с `init()` / `destroy()`.
- **TIBCO BusinessWorks 6 Adapter** — `AdapterLifecycle` interface.

Предложенный SPI — минимально достаточное подмножество (start/stop/health +
Registry) под текущие потребности проекта, без over-engineering'а.

## Критерии DoD ADR-022

- [ ] `src/infrastructure/clients/base_connector.py` создан с ABC.
- [ ] `src/infrastructure/registry.py` создан с Registry.
- [ ] `src/core/config/pooling.py` создан с `PoolingProfile`.
- [ ] `src/infrastructure/observability/client_metrics.py` создан.
- [ ] Хотя бы один клиент-pioneer (Redis или Postgres) мигрирован на ABC — как
  reference-имплементация для остальных.
- [ ] `docs/phases/PHASE_IL1.md` зафиксирован.
- [ ] Запись в `docs/adr/PHASE_STATUS.yml::IL1` со статусом `done` по закрытии.

## Ссылки

- План IL1-IL3: `/root/.claude/plans/tidy-jingling-map.md`.
- Knowledge graph проекта: `CLAUDE.md` (§14 resilience, §16 observability, §21 entrypoints).
