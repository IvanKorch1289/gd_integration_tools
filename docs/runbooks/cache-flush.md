# Runbook — Cache Flush

Безопасная инвалидация Redis-кэша уровня сервиса.

## Symptom
- Изменение cache_key invalidation logic.
- Stale-данные в UI после миграции.
- Признаки race-condition в кэш-слое.

## Cause
Намеренный refresh после изменения схемы / TTL / business rules.

## Resolution
1. Определить namespace: `redis-cli --scan --pattern 'gd:cache:*' | head`.
2. Сделать **точечный** flush:
   `redis-cli --scan --pattern 'gd:cache:orders:*' | xargs redis-cli del`.
3. **Никогда** `FLUSHALL` — он сносит rate-limit, locks, sessions.
4. После flush'а проверить SLO в течение 10 минут (cache miss → нагрузка БД).

## Verification
- `redis-cli dbsize` показывает ожидаемое снижение.
- p95 не выходит за SLO больше 5 мин.
- Сервисы продолжают отвечать 2xx.

## Rollback
Кэш — derived state, rollback не требуется. Если БД-нагрузка
поднялась критически — включить `cache_warmup` job через DSL.
