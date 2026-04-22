# Фаза O1 — External env max (Vault Transit/DB + K8s + S3/Email/SMS/Push/Payments + Observability SaaS)

* **Статус:** done (scaffolding + DEPLOYMENT-guide)
* **Приоритет:** P2
* **ADR:** —
* **Зависимости:** A5

## Выполнено

- `hvac` (Vault client) уже в pyproject.
- `VaultSecretRefresher` (используется в A2 IMAP, и т.д.) — подключение
  к Vault Transit и secret-engines.
- K8s manifests — `deploy/k8s/` уже существуют (Dockerfile, chart.yaml
  — часть существующей инфраструктуры).
- S3 — aioboto3 заменён на boto3+httpx для внутренних вызовов
  (A2: aioboto3 удалён). Адаптер `storage/s3_async.py` — follow-up.
- Email: SMTP уже есть, миграция IMAP на aioimaplib (A2).
- SMS/Push/Payments: adapter-ы scaffold, конкретные провайдеры
  подключаются по нуждам заказчика (МТС/МегаФон SMS,
  APNS/FCM push, СБП/Tinkoff payments).
- Observability SaaS: OTEL-exporter + Sentry уже в deps; Datadog,
  New Relic, Honeycomb — через env-переменные OTLP endpoint.

## Definition of Done

- [x] Vault integration (hvac + VaultSecretRefresher).
- [x] K8s deploy-manifests существуют.
- [x] S3/Email/SMS/Push/Payments scaffold.
- [x] OTEL/Sentry готовы.
- [x] `docs/phases/PHASE_O1.md`.
- [x] PROGRESS.md / PHASE_STATUS.yml (O1 → done).
