# Runbook — CDC Restart

Перезапуск Postgres CDC (logical replication slot) после сбоя.

## Symptom
- Метрика `cdc_lag_seconds` растёт.
- Нет событий из Postgres в Kafka/Rabbit.
- Replication slot inactive.

## Cause
- Сбой consumer'а.
- WAL retention исчерпан.
- Сетевая блокировка.

## Resolution
1. Проверить slot:
   ```sql
   SELECT slot_name, active, restart_lsn FROM pg_replication_slots;
   ```
2. Если `active = false`, перезапустить consumer:
   `kubectl rollout restart deploy/gd-cdc`.
3. Если `restart_lsn` зафиксирован — потенциально WAL truncated:
   - сбросить slot и пере-подписаться (`tools/cdc_reset.py`);
   - инициировать reconcile snapshot из source-таблицы.
4. После — мониторить lag 30 мин.

## Verification
- `cdc_lag_seconds` < 60.
- Тестовый INSERT в источнике появляется в downstream за <30 сек.
- Нет ошибок в логах consumer'а.

## Rollback
Если slot пересоздан с нуля и потеряли события:
1. Сделать manual reconcile через snapshot-job (см. `runbooks/audit-export.md`).
2. Сообщить downstream-командам о возможных дублях за окно простоя.
