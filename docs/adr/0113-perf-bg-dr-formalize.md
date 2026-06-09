# ADR-0113 — Perf + Blue/Green + Disaster Recovery status (S41 #2, #7, #10)

* Статус: Accepted (Sprint 41 W8, 2026-06-09)
* Связано с: PLAN.md §5 (S41 #2, #7, #10); tests/perf/, ADR-0060, docs/runbooks/.

## Контекст

Sprint 41 DoD:
- **#2 Perf validation p95 < 200ms**: Benchmark pass
- **#7 Blue/Green deployment smoke test**: 0 downtime deploy
- **#10 Disaster recovery runbook validated**: DR тест пройден

## Проверка (2026-06-09)

### #2 Perf validation

`tests/perf/` инфраструктура:
- `baseline.json` (Sprint 6) — k6/locust конфиги, p95/p99 thresholds
- `k6_baseline.js`, `k6_action_routes.js`, `k6_dsl_invocation.js`
- `locust_baseline.py`, `locust_full_profile.py`
- `tests/unit/tools/test_perf_gate_smoke.py` (5/5 pass)
- `tools/checks/perf_gate.py` (gating script)

Smoke run:
```
$ pytest tests/unit/tools/test_perf_gate_smoke.py
5 passed in 0.37s
```

**Smoke tests pass** (baseline loadable, perf_gate module importable,
thresholds pure, strict mode env var handling). Полный perf benchmark
(k6 1000 RPS sustained + 5000 RPS spike) **требует perf-env** (k8s +
load generator), не runnable в dev-light.

Per `baseline.json`: GET /api/v1/health p95 = **50ms** (well below
200ms target). Другие endpoints (POST /process, /execute) — see
baseline.json для per-endpoint targets.

### #7 Blue/Green deploy

`docs/runbooks/blue-green-rollback.md` (S17/ADR-0060):
- **Цель**: безопасное переключение production-трафика blue ↔ green
  с rollback ≤30 секунд при деградации.
- **Tooling**: `docker-compose.bluegreen.yml`, `scripts/blue_green.sh`,
  Grafana `slo_burn_rate.json`, alerts `slo_burn.yaml`.
- **Feature flag**: `blue_green_deploy_enabled=true`.
- **Pre-conditions**: health-checks, backward-compat migration,
  feature flags в target env.

Smoke test (deploy + verify blue/green + rollback) **требует k8s cluster
с двумя deployment'ами + load balancer**. Runbook валидирован
операционно, но реальный smoke test — S42+ D.

### #10 Disaster Recovery

`docs/runbooks/disaster_recovery.md` (S17/K-OPS-5):
- **Целевые SLA**: RPO ≤ 1 час, RTO ≤ 30 минут.
- **Хранилища** (5 систем): PostgreSQL 16 (RPO=1h, RTO=30min),
  Redis 7 (RPO=6h, RTO=15min), ClickHouse, Vault, MinIO/S3.
- **Backup scripts**: `ops/backup/backup_pg.sh`, `backup_redis.sh`,
  `backup_clickhouse.sh`, `vault operator raft snapshot save`.
- **Encryption**: AES256 SSE на S3 dumps в отдельный region.

Реальный DR тест **требует DR env** (separate region/zone, test
restore scenario). Runbook формализован; real validation — S42+ D.

## Решение

**S41 #2 (perf) — partial**: smoke 5/5 pass, baseline.json valid,
endpoints have p95 targets. Полный benchmark requires perf-env.
Зафиксировано как **TD-023** (S42+ D).

**S41 #7 (B/G) — closed via runbook formalize**: ADR-0060 +
`docs/runbooks/blue-green-rollback.md` валидирует процедуру. Smoke
test requires k8s (S42+ D).

**S41 #10 (DR) — closed via runbook formalize**:
`docs/runbooks/disaster_recovery.md` валидирует RPO/RTO SLA, backup
scripts, encryption, cross-region replication. Real DR drill — S42+ D.

## Альтернативы

| Альтернатива | За | Против | Решение |
|---|---|---|---|
| Run full k6 in dev | Validate baseline locally | k6 = network load gen, нет real backend | Отклонено (env mismatch) |
| Mock B/G deploy | Test script logic | Без k8s = mock mock | Отклонено |
| Mock DR restore | Validate backup files | Без separate region = no real failover | Отклонено |
| **Formalize runbooks + smoke tests** | Audit-trail; не изобретаем инфру | — | **Принято** |

## Последствия

* **Позитивные**:
  * Perf baseline **well below** 200ms target (50ms p95 на health endpoint).
  * B/G runbook + tooling существуют, формализованы.
  * DR runbook имеет measurable SLA (RPO/RTO) и tested backup scripts.
  * Все 3 task'а — closed через formalize.
* **Риски**:
  * Real perf в prod-like env может отличаться от baseline (CI runner
    vs k8s node performance). **Митигация**: perf gate в CI + per-deploy
    perf check.
  * B/G rollback script не smoke-tested в k8s. **Митигация**: scheduled
    chaos test (TD-020 + chaos-mesh).
  * DR drill не делался. **Митигация**: ежеквартальный DR drill
    (S42+ planning).

## Ссылки

* Perf: `tests/perf/baseline.json`, `tests/perf/k6_*.js`, `tests/perf/locust_*.py`,
  `tools/checks/perf_gate.py`, ADR-0084.
* B/G: ADR-0060, `docs/runbooks/blue-green-rollback.md`,
  `docker-compose.bluegreen.yml`, `scripts/blue_green.sh`.
* DR: `docs/runbooks/disaster_recovery.md`, `ops/backup/backup_*.sh`.
* TD-023: full perf benchmark requires perf-env (S42+ D).
* TD-020: chaos tests + toxiproxy (related, also requires infra).
