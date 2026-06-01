# Disaster Recovery Runbook

> **Sprint 17 / K-OPS-5 (DoD #14)** — операционный runbook восстановления после катастрофы.
> Целевые SLA: **RPO ≤ 1 час**, **RTO ≤ 30 минут**.

---

## Контекст

`gd_integration_tools` хранит данные в нескольких хранилищах:

| Хранилище | Назначение | RPO | RTO | Backup-скрипт |
|---|---|---|---|---|
| **PostgreSQL 16** | основные данные (orders, users, audit-meta, plugin state) | 1 час | 30 мин | `ops/backup/backup_pg.sh` |
| **Redis 7** | кэш, idempotency keys, RAG L1 | 6 часов | 15 мин | `ops/backup/backup_redis.sh` |
| **ClickHouse** | audit-log + metrics (если включён) | 24 часа | 1 час | `ops/backup/backup_clickhouse.sh` |
| **Vault (HCP/Self-hosted)** | секреты (DB-passwords, API-keys, mTLS-cert) | 24 часа | 1 час | `vault operator raft snapshot save` |
| **MinIO / S3** | артефакты RAG, отчёты, дампы | живая репликация | — | bucket replication |

Все дампы шифруются (`--sse AES256` для S3) и улетают в **отдельный region** для устойчивости к AZ-fail.

---

## Сценарий 1. PostgreSQL — потеря primary

**Симптом**: ``health_db`` red, alert ``pg_primary_down`` (Prometheus rule).

**Шаги (RTO ≤ 30 мин)**:

1. **Подтвердить недоступность primary**:
   ```bash
   docker exec gd-postgres pg_isready -U "${DB_USER}" || echo "PRIMARY DOWN"
   ```
2. **Активировать read-replica** (если включён `db_replica_enabled=true` в Sprint 13 W12):
   ```bash
   # На replica-инстансе:
   pg_ctl promote -D "${PGDATA}"
   # Поменять connection string в Vault (database/creds/app).
   ```
3. **Применить migrations** (если потеряны последние minutes):
   ```bash
   uv run alembic upgrade head
   ```
4. **Запустить readiness-check**:
   ```bash
   make readiness-check
   ```
5. **Если replica нет** — restore из последнего S3-дампа:
   ```bash
   bash ops/backup/restore_pg.sh "s3://${BACKUP_S3_BUCKET}/postgres/$(latest_dump)"
   ```
6. **Сообщить**: Slack `#ops`, status-page, обновить `docs/runbooks/incident-YYYY-MM-DD.md`.

**Проверка**: rolling 5-min p95 latency `/api/v1/orders` ≤ 100ms, error-rate < 1%.

---

## Сценарий 2. Vault — потеря секрет-стора

**Симптом**: `health_secrets` red, alert ``vault_unsealed=0``.

**Шаги (RTO ≤ 1 час)**:

1. **Восстановить Vault-инстанс** из snapshot:
   ```bash
   vault operator raft snapshot restore vault-snapshot-$(latest).snap
   ```
2. **Unseal** через quorum (3 из 5 ключей):
   ```bash
   vault operator unseal <key-1>
   vault operator unseal <key-2>
   vault operator unseal <key-3>
   ```
3. **Запустить ротацию** скомпрометированных credentials:
   ```bash
   uv run python tools/checks/check_pre_prod.py --only secrets_rotation
   ```
4. **Перезапустить app** (capability-gate reload + DI providers refresh):
   ```bash
   docker compose -f ops/compose/docker-compose.yml restart app
   ```

**Проверка**: `make security` + audit log содержит `secrets.rotated`-event.

---

## Сценарий 3. ClickHouse — потеря audit-кластера

**Симптом**: `audit-sink_backlog` > 10000, alert ``clickhouse_node_down``.

**Шаги (RTO ≤ 1 час)**:

1. **Активировать degradation level 2** (S13 W6 — graceful_degradation):
   ```bash
   # Через admin API:
   curl -X POST localhost:8000/api/v1/admin/degradation/set?level=2
   ```
   ClickHouse-audit отключается, fallback на PostgreSQL audit + Loki.

2. **Восстановить из последнего дампа**:
   ```bash
   clickhouse-backup restore "$(latest_backup_name)"
   ```
3. **Заполнить gap** из disk-rotating-fallback (LogSink ABC, S13):
   ```bash
   bash ops/backup/replay_audit_disk_buffer.sh /var/lib/audit/disk-rotating/
   ```
4. **Снять degradation**:
   ```bash
   curl -X POST localhost:8000/api/v1/admin/degradation/set?level=0
   ```

**Проверка**: `audit-sink_backlog` < 100, дашборд `Audit Health` зелёный.

---

## Сценарий 4. Plugin rollback — критический баг в V11 plugin

**Симптом**: alert ``plugin_error_rate{plugin="<name>"} > 5%`` или manual report.

**Шаги (RTO ≤ 15 мин)**:

1. **Отключить плагин через capability-gate**:
   ```bash
   # PluginLoader hot-reload (FF v11.hot_reload_enabled=true):
   touch extensions/<name>/.disabled
   ```
   Capabilities автоматически revoke'аются (см. `PluginLoader.shutdown_one`).

2. **Альтернатива (без hot-reload)** — feature_flag в admin:
   ```bash
   curl -X POST localhost:8000/api/v1/admin/plugins/<name>/disable
   ```

3. **Rollback версии** (если плагин нужен но в старой версии):
   ```bash
   cd extensions/<name>/ && git checkout v<previous-tag>
   docker compose restart app
   ```
4. **Audit-event** ``plugin.rollback`` появится в ClickHouse-audit автоматически.

**Проверка**: error-rate плагина < 0.1% за 5 мин.

---

## Регулярная проверка DR (chaos-quarter)

Раз в квартал (последняя неделя каждого квартала):

1. Запустить `bash ops/backup/restore_pg.sh ... && make pre-prod-check`.
2. Проверить, что `restore_pg.sh` действительно работает на свежем дампе.
3. Обновить этот runbook датой последней успешной проверки.

**Последняя успешная DR-проверка**: _(заполнить после первого quarterly chaos)_.

---

## Контакты и эскалация

- **On-call DBA** — `#ops-db`
- **Security incidents** — `#security-incidents` + GPG-encrypted email.
- **Vault key holders** — 5 человек (квартальная ротация).
- **External provider escalation** (cloud DB) — см. внутренний wiki, не сюда.

---

## Связанные wave/ADR

- ADR-NEW-5 — graceful degradation (Sprint 13 W6).
- ADR-NEW-7 — secrets rotation (Sprint 9 K1 W2).
- ADR-043 — RouteLoader V11 (Sprint 11+).
- S21 W8 — Workflow state SQLAlchemy persistence (saga recovery).
- S17 K2 W3 — TaskRegistry watchdog (leak prevention).

---

**Версия runbook**: v0.1 (Sprint 17, K-OPS-5 scaffold).
**Carryover в S18**: chaos-tests `make chaos` для каждого сценария; runbook-test-runner CI.

---

## Post-Incident Analysis (RCA / Root Cause Analysis)

После каждого DR-инцидента обязательно проведение **Root Cause Analysis**:

1. **Таймлайн**: точное время деградации / восстановления по логам (`dr_backup_age_seconds`, `pagerduty` события).
2. **Root cause (причина)**: что именно вызвало disaster (network partition, data corruption, human error, dependency outage).
3. **Detection latency**: сколько времени от инцидента до первого alert'а.
4. **MTTR (Mean Time To Recovery)**: фактический vs target (SLO p95).
5. **Action items**:
   - что добавить в этот runbook;
   - что вынести в ADR (если архитектурное);
   - что автоматизировать (chaos-test, alert, runbook-test-runner).
6. **Анализ тренда**: повторяется ли этот класс инцидентов? (RCA history за 90 дней)

RCA-документ хранится в `vault/incidents/<YYYY-MM-DD>-<short-slug>.md` и линкуется в
этот runbook в секции "Incident log" после события.
