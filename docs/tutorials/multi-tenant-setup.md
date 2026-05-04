# Tutorial — Multi-tenant Setup

Цель: изолировать данные нескольких tenant'ов на одном инстансе.

## Что вы узнаете
- Как пометить запросы `tenant_id`.
- Как настроить tenant-aware кэш.
- Как фильтровать audit-логи.

## Шаги

1. Включите middleware tenant-resolver — header `X-Tenant-Id`
   автоматически попадает в `request.state.tenant_id`.
2. В сервисе используйте `tenant_id` как часть cache_key:
   ```python
   key = f"orders:{tenant_id}:{order_id}"
   ```
3. Для RAG namespace = `tenant_id`:
   ```bash
   curl -X POST /api/v1/rag/ingest \
        -H "X-Tenant-Id: acme" \
        -d '{"content":"…","namespace":"acme"}'
   ```

## Проверка
- `/api/v1/search/logs?tenant_id=acme` возвращает только записи `acme`.
- В метриках видны лейблы `tenant=acme`.

## Next steps
- [RAG setup](rag-setup.md)
- [DB migration](../runbooks/db-migration.md)
