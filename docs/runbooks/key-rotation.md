# Runbook — Key Rotation

Ротация секретов: API keys, JWT signing keys, Vault tokens.

## Symptom
- Плановая ротация (квартально).
- Подозрение на компрометацию.
- Инцидент с утечкой.

## Cause
Compliance + защита от длительной экспозиции секрета.

## Resolution
1. Сгенерировать новый secret (Vault transit / HSM).
2. Залить в Vault: `vault kv put secret/gd/<name> value=<new>`.
3. Откатить новые поды: `kubectl rollout restart deploy/gd-api`.
4. После 100% rollout — пометить старый secret как `deprecated`,
   но **не** удалять до конца audit-периода (24ч).
5. По истечению — `vault kv metadata delete secret/gd/<name>@v<old>`.

## Verification
- `/api/v1/health/check_all_services` → 200.
- В логах нет 401/403 за время rollout'а > 1 мин.
- Старый secret не работает: `curl -H 'X-API-Key: <old>'` → 401.

## Rollback
Если новый secret сломал интеграцию:
1. Восстановить старое значение из Vault audit log.
2. Перезалить и rollout deploy.
3. Сообщить в `#ops` + завести ADR о проблеме формата.
