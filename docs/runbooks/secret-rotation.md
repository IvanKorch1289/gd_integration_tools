# Runbook: ротация секретов через Vault

**Wave**: `[wave:s8/k1-security-runbooks]`
**Owner**: K1 Security
**Связано**: `infrastructure/security/vault_secrets.py`, `[wave:s8/k1-vault-rotation]`,
memory `feedback_wave_s1_security`.

## Когда запускать

* Плановая ротация (квартал) для long-lived креденшалов БД, S3, MQ.
* Внеплановая: после инцидента / увольнения сотрудника / утечки артефакта.
* Auto-trigger: Vault lease ttl истёк (см. `VaultSecretRotator` background-job).

## Action / Trigger / Checklist

### Action — что произойдёт

1. `VaultSecretRotator` вызывает `vault.kv.v2.create_or_update_secret(...)` с
   новым value.
2. `SecretBroker` бросает `SecretRotated` event на in-memory bus.
3. Подписчики (DB pool, OutboundHttpClient, MQ producer) пере-инициализируют
   соединения с новым креденшалом без рестарта приложения.
4. Старый секрет remains в Vault как version=N-1 (audit trail).

### Trigger — как запустить вручную

```bash
# 1. Подключиться к prod-кластеру Vault через vault CLI:
export VAULT_ADDR=https://vault.internal:8200
vault login -method=oidc

# 2. Сгенерировать новый секрет (пример: PostgreSQL пароль):
new_pw=$(openssl rand -hex 32)

# 3. Записать в Vault:
vault kv put secret/gd_integration_tools/postgres password="$new_pw"

# 4. Триггерить broker — POST к /admin/secrets/refresh (требует admin JWT):
curl -X POST https://api.gd-integration.internal/api/v1/admin/secrets/refresh \
     -H "Authorization: Bearer $ADMIN_JWT" \
     -d '{"key": "secret/gd_integration_tools/postgres"}'
```

### Checklist — после ротации

- [ ] Новые соединения используют новый секрет: `pg_stat_activity` показывает
      успешные `pg_authentication_succeeded` events.
- [ ] Старые pending транзакции завершились без ошибок.
- [ ] Audit-event `secret.rotated` записан (см. `audit/immutable_audit`).
- [ ] Метрика `secret_rotation_success_total` увеличилась.
- [ ] Уведомить on-call в `#oncall-platform` (Slack).

## Откат

Если новый секрет некорректен (e.g., неверная политика IAM):

```bash
# Восстановить предыдущую версию:
vault kv rollback -version=N-1 secret/gd_integration_tools/postgres

# Триггерить refresh снова.
curl -X POST .../admin/secrets/refresh -d '{"key": "..."}'
```

## Ссылки

* PLAN.md §V15 R-V15-11 (Vault rotation).
* Memory `feedback_wave_s1_security`, `feedback_wave_k1_security`.
