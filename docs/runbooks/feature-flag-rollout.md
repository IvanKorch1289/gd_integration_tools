# Runbook: Flagsmith feature-flag rollout

> Status: Sprint 9 K1 W4 — staging rollout процедура.
> Owner: K1 Security.

## Symptom

Команда хочет переключить feature-flag backend с in-memory на Flagsmith
(external SaaS / self-hosted Flagsmith API), что обеспечивает централизованное
управление флагами без redeploy и поддержку tenant-targeting (V11).

## Pre-conditions

* Flagsmith instance развернут в `compose/docker-compose.staging.yml` (или
  self-hosted SaaS endpoint).
* `FLAGSMITH_API_URL` и `FLAGSMITH_ENV_KEY` доступны в Vault под
  `secrets/flagsmith/{api_url,env_key}`.
* В Flagsmith UI созданы 5 environment'ов: `dev`, `staging`, `pre-prod`,
  `prod-eu`, `prod-ru`.
* CI-pipeline `feature-flag-sync.yml` синхронизирует `core/config/features.py`
  → Flagsmith (для нового provisioning'а).

## Diagnosis

1. Проверить статус OpenFeature provider:
   ```bash
   curl -s http://<api>/api/v1/admin/feature-flags/backend-status
   # ожидаемый ответ:
   # {"backend": "in-memory", "ready": true, "flags_count": 47}
   ```

2. Проверить, что core/config/features.py имеет hot-toggle (Sprint 9):
   ```bash
   .venv/bin/python -c "from src.backend.core.config.features import feature_flags; print(feature_flags.openfeature_flagsmith_backend)"
   # должно быть False (default-OFF до этого runbook'а)
   ```

## Mitigation (rollout)

### Stage 1: staging smoke test (зелёный)

1. В staging compose файле добавить:
   ```yaml
   environment:
     FEATURE_FLAG_BACKEND: flagsmith
     FLAGSMITH_API_URL: ${FLAGSMITH_API_URL}
     FLAGSMITH_ENV_KEY: ${FLAGSMITH_ENV_KEY_STAGING}
   ```

2. `docker compose -f docker-compose.staging.yml up -d`.

3. Smoke-test:
   ```bash
   curl -s http://<staging>/api/v1/admin/feature-flags/backend-status | jq
   # backend должно быть "flagsmith"
   ```

4. Прогнать e2e suite: `make test-e2e ENV=staging` → 100% pass.

5. Мониторить Grafana dashboard `flagsmith-resolution-latency` 24h:
   p95 < 50ms, error_rate < 0.1%.

### Stage 2: pre-prod canary (10%)

1. В `compose/docker-compose.preprod.yml` поднять `FEATURE_FLAG_BACKEND=flagsmith`
   на 1 из 10 реплик через k8s deployment annotation `flagsmith-canary=true`.

2. Мониторить error_rate × 24h. Если выше staging baseline +20% — rollback.

### Stage 3: production rollout

1. Переключить `pre-prod-100%` для канареечного теста (4 часа observation).

2. Если baseline стабилен — rollout `prod-eu` затем `prod-ru` поэтапно
   (4-6 часов между этапами).

3. Финальный шаг — обновить `core/config/features.py::openfeature_flagsmith_backend`
   default в True (отдельный PR с changelog).

## Verification

* `make check-feature-flags` — gate проходит (default-OFF новых флагов).
* p95 resolution latency < 50ms (Grafana).
* Zero feature-flag errors в Sentry за 24h после rollout.
* `make audit-feature-flags` — все flags имеют owner=K1-K5.

## Rollback

При любом sustained error_rate spike:

1. `kubectl set env deploy/<service> FEATURE_FLAG_BACKEND=in-memory`.
2. Restart pods.
3. Открыть RCA-ticket с timestamp начала проблемы.

## Postmortem template

```
## Что случилось
<краткая хронология>

## Impact
<кол-во затронутых запросов, tenant'ов, время>

## Root cause
<техническая причина>

## Mitigation
<что сделали для устранения>

## Action items
- [ ] ...
```

## References

* ADR-0061 — WAF allowlist tightening
* PLAN.md V19.1 §S9 K1 W4
* `src/backend/core/feature_flags/flagsmith_provider.py`
