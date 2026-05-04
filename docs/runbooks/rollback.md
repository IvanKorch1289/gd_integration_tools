# Runbook — Rollback

Откат на предыдущий стабильный релиз.

## Symptom
- Свежий деплой увеличил ошибки 5xx.
- Регрессия в actions / DSL.
- Health/ready нестабилен.

## Cause
Несовместимое изменение в коде, конфиге или миграциях.

## Resolution
1. Заморозить релизы: остановить CI на `master`.
2. Зафиксировать причину в `vault/incident-YYYY-MM-DD.md`.
3. Откатить образ: redeploy тега предыдущего успешного релиза.
4. При необходимости — `alembic downgrade -1`.
5. Сообщить об инциденте в `#ops`.

## Verification
- `/api/v1/health/ready` → 200.
- 5xx-rate возвращается к baseline (Grafana).
- Метрика `app_version` совпадает с тегом отката.

## Rollback
Этот runbook — сам по себе rollback. Если откат не помог — escalate.
