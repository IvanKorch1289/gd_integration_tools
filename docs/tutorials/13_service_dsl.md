# ServiceDSL — декларативная регистрация сервисов с авто-созданием endpoints

`@service_dsl` автоматически регистрирует сервис в ActionHandlerRegistry,
после чего он становится доступен через REST, gRPC, SOAP, GraphQL, MQ, WS, SSE,
MCP, MQTT (multi-protocol auto-registration согласно R-V15-3).

## Декоратор @service_dsl

```python
# source: src/backend/dsl/service_dsl.py:93-150
from pydantic import BaseModel
from src.backend.dsl.service_dsl import service_dsl

class InvoiceIn(BaseModel):
    customer_id: str
    amount: float

class InvoiceOut(BaseModel):
    invoice_id: str
    status: str

@service_dsl(
    name="invoices",
    schema_in=InvoiceIn,
    schema_out=InvoiceOut,
    protocols=["all"],
    crud=True,
)
class InvoiceService:
    async def create(self, data: InvoiceIn) -> InvoiceOut:
        ...

    async def approve(self, invoice_id: str) -> InvoiceOut:
        ...
```

Параметры:

| Параметр | Тип | Описание |
|----------|-----|----------|
| `name` | `str` | Имя сервиса (namespace для actions) |
| `schema_in` | `type[BaseModel]` | Pydantic-модель входящего payload |
| `schema_out` | `type[BaseModel]` | Pydantic-модель результата |
| `protocols` | `Sequence[str]` | `["all"]` или конкретные: `["rest", "grpc"]` |
| `crud` | `bool` | Авто-регистрация `.add/.get/.update/.delete` |
| `methods` | `Sequence[str]` | Явный список методов (иначе — все public) |

## service.toml (декларативный вариант)

Вместо Python-декоратора можно описать сервис в TOML:

```toml
# extensions/credit/services/credit.service.toml
name = "credit"
version = "1.0.0"
tenant_aware = true

[capabilities]
fs.read = ["extensions/credit/data/*"]
net.outbound = ["credit-bureau.example.com:443"]

[timeouts]
connect = 5.0
read = 30.0

[resilience]
retry_attempts = 3
circuit_breaker_threshold = 10
```

Загрузка — через `ServiceDSLRegistry`:

```python
# source: src/backend/dsl/service/registry.py
from src.backend.dsl.service.registry import get_service_registry

registry = get_service_registry()
spec = registry.get("credit")
print(spec.name, spec.version)
```

## Auto-registration действий

При `crud=True` регистрируются 4 action'а:

| Action | Метод | Описание |
|--------|-------|----------|
| `invoices.add` | `create` | Создание |
| `invoices.get` | `get` | Получение |
| `invoices.update` | `update` | Обновление |
| `invoices.delete` | `delete` | Удаление |

Дополнительные методы (не CRUD) регистрируются автоматически:

```python
@service_dsl(name="invoices", crud=True)
class InvoiceService:
    async def send_reminder(self, invoice_id: str) -> None:
        # → invoices.send_reminder
        ...

    async def approve(self, invoice_id: str, approver: str) -> InvoiceOut:
        # → invoices.approve
        ...
```

## Programmatic access

```python
# source: src/backend/dsl/service_dsl.py:61-62
from src.backend.dsl.service_dsl import service_dsl_registry

for meta in service_dsl_registry.list_services():
    print(f"{meta.name}: {len(meta.methods)} methods, protocols={meta.protocols}")
```

## Multi-protocol auto-registration (D-AUDIT-101, partial)

**Reality check (D-AUDIT-101, 2026-08-05)**: только REST auto-генерируется через
`entrypoints/api/generator/auto_register.py` (V22-6, Sprint 6). Остальные
протоколы (SOAP/gRPC/GraphQL/WS/SSE/MQ/MQTT/MCP) подключаются вручную
через `include_router(...)` в `src/backend/plugins/composition/app_factory.py`
(см. `docker_admin_router`, `graphql_router`, `soap_router`, `ws_router`,
`mcp_router`).

Документация ниже описывает **target architecture (R-V15-3)** vs **текущая
реализация**. Multi-protocol auto-registration as a single 1-action
deploys-to-all-protocols feature is NOT yet shipped (separate ADR-level
work, see `KNOWN_ISSUES.md` carry-over).

### Currently shipped (per protocol)

```
REST  POST   /api/v1/auto/<action>    → @register_action (auto-generated)
SOAP  POST   /soap/<route>           → include_router(soap_router) (manual)
gRPC  rpc    <Service>.<Method>      → auto_servicer (manual setup in app_factory)
GraphQL mutation <action>           → include_router(graphql_router) (manual)
WS    ws://  /<route>/subscribe     → include_router(ws_router) (manual)
SSE   GET    /<route>/events         → include_router(sse_router) (manual)
MCP   tool   <action>                → include_router(mcp_router) (manual)
MQTT  topic  <action>                → include_router(mqtt_router) (manual)
MQ    queue: <action>                → include_router(mq_router) (manual)
CDC   subscription <table>           → include_router(cdc_routes) (manual)
```

### Target architecture (R-V15-3, not yet shipped)

```
One registered @register_action auto-deploys to ALL protocols above.
See docs/architecture/ for ADR on R-V15-3 work split.
```

## Регистрация через scan

```python
# source: src/backend/dsl/service_dsl.py:204-253
from src.backend.dsl.service_dsl import scan_and_register_actions

# Сканирует все модули в пакете и регистрирует @register_action
count = scan_and_register_actions(package_paths=["extensions.credit.functions"])
print(f"Зарегистрировано {count} actions")
```

## Метод-level декоратор

Точечная регистрация отдельного метода без полного класса:

```python
# source: src/backend/dsl/service_dsl.py:160-190
from src.backend.dsl.service_dsl import register_action

class OrderService:
    @register_action("orders.create_skb_order", payload_model=OrderIdSchema)
    async def create_skb_order(self, data):
        ...
```

## Startup-инициализация

В `src/backend/plugins/composition/lifecycle.py`:

```python
async def on_startup() -> None:
    from src.backend.dsl.service_dsl import service_dsl_registry
    service_dsl_registry.register_all_actions()
```

## Feature flag

Default-OFF через `feature_flags.service_toml_loader`: при выключенном
флаге `register()` игнорирует входной spec.

## См. также

- `src/backend/dsl/service_dsl.py` — полная реализация
- `src/backend/dsl/service/registry.py` — ServiceDSLRegistry singleton
- `docs/tutorials/01_build_first_action.md` — создание action с нуля