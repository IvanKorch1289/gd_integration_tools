# Tutorial — Write a DSL route

Цель: описать интеграционный маршрут через DSL и запустить.

## Что вы узнаете
- Базовый синтаксис DSL Builder.
- Как зарегистрировать pipeline.
- Как протестировать через REST/MCP.

## Шаги

1. Создайте `dsl_routes/orders_to_warehouse.yaml`:
   ```yaml
   route_id: orders.to_warehouse
   source: rabbitmq:queues.orders
   description: Заказы → polars-агрегация → S3.
   processors:
     - DecodeBody:
         format: json
     - Filter:
         predicate: "$.status == 'NEW'"
     - PolarsTransform:
         expr: "df.group_by('region').sum()"
     - S3Sink:
         bucket: warehouse
         key: orders/{date}.parquet
   ```
2. Перезапустите `make dev-light`.
3. Запустите вручную:
   ```bash
   curl -X POST /api/v1/dsl_console/run -d '{"route_id":"orders.to_warehouse"}'
   ```

## Проверка
- `make routes | grep orders.to_warehouse`.
- Файл в S3 появился.

## Next steps
- [DSL templates library](https://docs/DSL_COOKBOOK.md)
- [Workflow engineering](../DEVELOPER_GUIDE.md)
