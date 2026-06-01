# Runbook: incident response (PII / security)

**Wave**: `[wave:s8/k1-security-runbooks]`
**Owner**: K1 Security
**Связано**: `services/security/pii_pipeline.py`, `audit/immutable_audit`.

## Триггеры

* SIEM-алерт: `security.pii.leak.detected` (PII pipeline нашёл utterance с
  данными за пределами allowed scope).
* SOC уведомление о подозрительной активности (массовый внешний доступ).
* Self-report сотрудника (случайно закоммитил secret в git и т.п.).

## Phase 1 — Триаж (≤ 15 минут)

1. **Зафиксировать timestamp** инцидента — точный T0 для restore-window.
2. **Идентифицировать scope**:
   - какой tenant пострадал? (`audit.events WHERE event=...`).
   - какие PII-категории затронуты (Ф.И.О. / документы / финансы).
   - utterance-level: на каком DSL-шаге произошёл leak.
3. **Заморозить состояние**: `make freeze-tenant TENANT=<id>` —
   останавливает входящие webhooks + блокирует workflow на этом tenant'е.
4. Создать инцидент в Jira `SEC-XXX` с шаблоном из
   `docs/explanation/sec-incident-template.md`.

## Phase 2 — Контейнмент (≤ 1 час)

1. Если утечка через webhook → отозвать соответствующий API-key
   (`/api/v1/admin/api-keys/<id>/revoke`).
2. Если утечка через cloud LLM → вызвать `langfuse.trace.delete(...)` для
   удаления sensitive prompt'ов (см. `services/ai/observability/langfuse`).
3. Если утечка через лог → запустить `tools/audit/redact_logs.py
   --window <T0>..<T_now>` (заменяет PII на `<redacted>` в Graylog индексе).

## Phase 3 — Eradication + Recovery

1. Patch root cause (capability-gate, output-filter, schema-validator).
2. Прогнать `make security-review BRANCH=hotfix/<id>`.
3. Cherry-pick hotfix → master с тегом `[wave:hotfix/sec-<id>]`.
4. После merge: `make unfreeze-tenant TENANT=<id>`.
5. Проверить chaos-test'ами что сценарий не воспроизводится.

## Phase 4 — Post-incident

* Заполнить post-mortem в `vault/incidents/sec-<id>-postmortem.md`.
* Обновить memory: новая запись типа `feedback` с описанием правила
  «как впредь не допустить».
* Если затронуты внешние стороны (клиент, регулятор) — уведомить через
  юристов в течение 72ч (GDPR-style требование банка).

## Audit chain

Любая операция инцидента пишется в `immutable_audit`:

```sql
SELECT event_id, actor, action, resource, timestamp
FROM audit_events
WHERE category='security_incident' AND incident_id='SEC-XXX'
ORDER BY timestamp;
```

## Ссылки

* `services/security/pii_pipeline.py` — детектор PII в utterance.
* PLAN.md §V19 (OWASP API Top 10).
* Memory `feedback_wave_k1_security`.
