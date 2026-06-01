# Temporal mTLS Rotation — Runbook

> **Sprint 12 K1 W2** — production-ready mTLS Temporal worker → server через Vault PKI engine.

## Контекст

Temporal workers подключаются к Temporal server по mTLS. Сертификаты выдаются
Vault PKI engine с TTL=24h. Workers автоматически обновляют сертификаты
через `TaskRegistry` за 1h до истечения.

**Feature-flag**: `workflow_mtls_enabled` (default-OFF до staging-smoke).

## Подготовка PKI engine (one-time)

```bash
# 1. Включить PKI secrets engine
vault secrets enable -path=pki pki

# 2. Настроить max lease TTL
vault secrets tune -max-lease-ttl=87600h pki

# 3. Сгенерировать root CA
vault write -field=certificate pki/root/generate/internal \
    common_name="gd_integration_tools CA" \
    ttl=87600h > /tmp/ca.pem

# 4. Создать role для Temporal worker
vault write pki/roles/temporal-worker \
    allowed_domains=temporal-worker,localhost \
    allow_subdomains=true \
    max_ttl=24h \
    require_cn=false

# 5. Verify
vault write pki/issue/temporal-worker \
    common_name=temporal-worker \
    ttl=24h
```

## Активация в проекте

1. `feature_flags.workflow_mtls_enabled = True`.
2. Установить env:
   - `VAULT_ADDR=http://vault:8200`;
   - `VAULT_TOKEN=<role-bound-token>`.
3. В composition root:
   ```python
   TemporalClientFactory(
       target_host="temporal:7233",
       pki_backend="vault",
       pki_role="temporal-worker",
       pki_common_name="temporal-worker",
       pki_ttl="24h",
   )
   ```

## Cert rotation (manual)

```bash
# Revoke current token (forces fresh issue)
vault token revoke <token>

# Worker reconnect автоматически через factory cache invalidation
# (или через explicit invalidate):
python -c "from src.backend.infrastructure.secrets.vault_pki import VaultPkiClient; VaultPkiClient().invalidate(role='temporal-worker', common_name='temporal-worker')"
```

## Smoke-test

```bash
docker-compose -f docker-compose.bluegreen.yml up -d temporal worker
docker-compose -f docker-compose.bluegreen.yml logs worker | grep -i "connected"
```

Ожидаемо: `temporal.client.connecting`, `worker connected to temporal:7233`.

## Rollback на file-based certs

Если Vault недоступен — фабрика автоматически fallback на `file` backend:
прочитает `tls.cert`, `tls.key`, `tls.ca` из config. Установить:

```python
TemporalClientFactory(
    pki_backend="file",
    tls={"cert": "/etc/temporal/cert.pem", ...},
)
```
