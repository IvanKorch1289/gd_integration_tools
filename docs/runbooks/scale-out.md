# Runbook — Scale-out

Горизонтальное масштабирование backend (granian + taskiq workers).

## Symptom
- p95 latency > SLO.
- CPU/RAM на одной ноде > 80% устойчиво.
- Очередь taskiq растёт.

## Cause
- Рост трафика, не успевающего за единственной репликой.
- Долгие фоновые задачи блокируют worker'ов.

## Resolution
1. Увеличить число реплик granian:
   `kubectl scale deploy/gd-api --replicas=N`.
2. Поднять отдельные taskiq-воркеры:
   `make taskiq-worker WORKERS=4` (см. `docs/runbooks/taskiq-worker.md`).
3. Если bottleneck — БД, открыть отдельный runbook `db-migration.md`
   (read-replica).

## Verification
- p95 latency возвращается ниже SLO.
- Очередь taskiq ↓ к нулю за 10 мин.
- Equal распределение запросов между подами (Grafana).

## Rollback
- `kubectl scale deploy/gd-api --replicas=1` (либо предыдущее значение).
- Остановить лишних taskiq-воркеров.
