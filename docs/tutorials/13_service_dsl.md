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

## Multi-protocol auto-registration

Один зарегистрированный сервис автоматически доступен через:

```
REST  POST   /api/invoices          → invoices.add
gRPC  rpc    AddInvoice(...)        → invoices.add
SOAP  POST   /soap/invoices         → invoices.add
GraphQL mutation addInvoice         → invoices.add
MQ    queue: invoices.add           → invoices.add
WS    ws://  /invoices/subscribe    → invoices.add
SSE   GET    /sse/invoices          → invoices.add
MCP   tool   invoices_add           → invoices.add
MQTT  topic  invoices/add           → invoices.add
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