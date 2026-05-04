# Runbook — Incident Response

Базовая процедура реагирования на P1/P2 инциденты.

## Symptom
- Алерт в `#ops` (Grafana / Prometheus / Sentry).
- 5xx-rate > 1% за 5 мин.
- Health/ready падает.

## Cause
Любая: упал внешний сервис, регрессия, исчерпание ресурсов, утечка.

## Resolution
1. **Acknowledge** алерт в течение 5 минут.
2. **Triage**: открыть `vault/incident-YYYY-MM-DD-HHMM.md`,
   зафиксировать первый snapshot метрик.
3. Локализовать домен: `make actions`, `/api/v1/health/check_all_services`.
4. Если виновник — последний релиз → `runbooks/rollback.md`.
5. Если внешний — изолировать (circuit-breaker / feature flag):
   `tools/feature_flags.py disable <flag>`.
6. Сообщить об инциденте в `#ops` с текущим статусом.

## Verification
- 5xx-rate возвращается к baseline.
- Health/ready стабилен 15 минут.
- Алерт автоматически разрешается.

## Rollback
Зависит от причины. Стандартный — рестарт+rollback (`runbooks/rollback.md`).

## Postmortem
В течение 48ч:
- заполнить `vault/incident-YYYY-MM-DD.md`;
- зарегистрировать ADR при системном изменении;
- обновить runbook'и при новых выводах.
