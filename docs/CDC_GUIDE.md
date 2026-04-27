# CDC Guide — Change Data Capture

Подписка на изменения в таблицах внешних БД с тремя стратегиями:
polling, PostgreSQL LISTEN/NOTIFY, Oracle LogMiner.

## Выбор стратегии

| Стратегия | БД | Latency | Сложность |
|---|---|---|---|
| `polling` | Любая (PG/Oracle/MySQL) | ~5-60s | Нулевая (просто `updated_at` column) |
| `listen_notify` | PostgreSQL | < 100ms | Требует trigger на таблице |
| `logminer` | Oracle | ~1-10s | Требует прав `SELECT ANY TRANSACTION` |

## Polling стратегия (универсальная)

Работает с любой БД через `updated_at` (или другой timestamp column):

```python
route = (
    RouteBuilder.from_("cdc.orders_polling", source="internal:cdc")
    .cdc(
        profile="pg_main",              # профиль из external_databases config
        tables=["orders", "payments"],
        target_action="cdc.on_change",  # куда слать события
        strategy="polling",
        interval=10.0,                  # опрос каждые 10 секунд
        timestamp_column="updated_at",  # колонка для отслеживания
        batch_size=100,                 # макс за итерацию
    )
    .build()
)
```

**Требования:** таблица должна иметь `updated_at` (или указанный timestamp column),
обновляемый при INSERT и UPDATE. DELETE не обнаруживается.

**Событие:**
```json
{
  "operation": "UPSERT",
  "table": "orders",
  "timestamp": "2026-04-19T12:00:00+00:00",
  "profile": "pg_main",
  "new": {"id": 123, "status": "active", "updated_at": "..."}
}
```

## PostgreSQL LISTEN/NOTIFY (low-latency)

Real-time уведомления через pg_notify — latency < 100ms.

### Шаг 1: Создайте trigger в БД

```sql
CREATE OR REPLACE FUNCTION notify_cdc_orders() RETURNS TRIGGER AS $$
BEGIN
    PERFORM pg_notify('cdc_orders', json_build_object(
        'operation', TG_OP,
        'table', TG_TABLE_NAME,
        'new', row_to_json(NEW),
        'old', row_to_json(OLD)
    )::text);
    RETURN COALESCE(NEW, OLD);
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER cdc_orders_trigger
AFTER INSERT OR UPDATE OR DELETE ON orders
FOR EACH ROW EXECUTE FUNCTION notify_cdc_orders();
```

### Шаг 2: Подписка в DSL

```python
.cdc(
    profile="pg_main",
    tables=["orders"],
    target_action="cdc.on_change",
    strategy="listen_notify",
    channel="cdc_orders",  # или оставить default
)
```

**Событие:** содержит `operation` (INSERT/UPDATE/DELETE), `new`, `old`.

## Oracle LogMiner (база на redo logs)

Требует права: `SELECT ANY TRANSACTION`, `EXECUTE_CATALOG_ROLE`.

Предварительно нужно включить supplemental logging:
```sql
ALTER DATABASE ADD SUPPLEMENTAL LOG DATA;
ALTER TABLE orders ADD SUPPLEMENTAL LOG DATA (ALL) COLUMNS;
```

Запустить LogMiner (DBA):
```sql
BEGIN
  DBMS_LOGMNR.START_LOGMNR(
    OPTIONS => DBMS_LOGMNR.DICT_FROM_ONLINE_CATALOG +
               DBMS_LOGMNR.CONTINUOUS_MINE
  );
END;
```

### Подписка в DSL

```python
.cdc(
    profile="oracle_prod",
    tables=["ORDERS", "PAYMENTS"],  # ВЕРХНИЙ регистр важен для Oracle
    target_action="cdc.on_change",
    strategy="logminer",
    interval=5.0,
    batch_size=500,
)
```

**Событие:** `operation` (INSERT/UPDATE/DELETE), `new` = `{"_sql_redo": "...", "_scn": ...}`.

## Обработка событий

Ваш action получает стандартное CDC-событие в payload:

```python
@register_action("cdc.on_change")
async def on_change(
    self,
    operation: str,
    table: str,
    timestamp: str,
    profile: str,
    new: dict | None = None,
    old: dict | None = None,
) -> dict:
    if operation == "INSERT":
        await self.index_new_record(table, new)
    elif operation == "UPDATE":
        await self.update_index(table, new, old)
    elif operation == "DELETE":
        await self.remove_from_index(table, old)
    return {"processed": True}
```

## ETL Pipeline через CDC

```python
# Source: CDC events → Transform → Load
route = (
    RouteBuilder.from_("etl.cdc_to_analytics", source="cdc:orders")
    .cdc(
        profile="pg_main",
        tables=["orders"],
        target_action="etl.process_cdc",
        strategy="listen_notify",
    )
    .build()
)

# Отдельный route для обработки:
etl_route = (
    RouteBuilder.from_("etl.process_cdc", source="internal:etl")
    .normalize()
    .transform("new")   # извлекаем new row
    .dispatch_action("analytics.insert_event")
    .build()
)
```

## Управление подписками

```python
from src.infrastructure.clients.external.cdc import get_cdc_client

client = get_cdc_client()

# Список активных подписок
subs = client.list_subscriptions()

# Отписка
await client.unsubscribe("sub_id_abc123")

# Graceful shutdown всех подписок
await client.shutdown()
```

## Troubleshooting

**Polling не видит изменений:**
- Проверьте что `updated_at` обновляется в таблице
- Убедитесь в правильном `timestamp_column`

**LISTEN/NOTIFY не срабатывает:**
- Проверьте trigger: `SELECT * FROM pg_trigger WHERE tgname LIKE 'cdc_%';`
- Убедитесь что `channel` совпадает с тем что в pg_notify

**LogMiner требует прав:**
- `GRANT SELECT ANY TRANSACTION TO cdc_user;`
- `GRANT EXECUTE ON DBMS_LOGMNR TO cdc_user;`
- Включите supplemental logging (см. выше)
