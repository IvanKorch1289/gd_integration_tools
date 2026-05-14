# ADR-0060 — Blue/Green deployment topology

* Статус: Accepted (Sprint 7 K2, 2026-05-14)
* Связано с: PLAN.md V18.2 §S7 К2, V15 R-V15-10 (auto-scaling), R-V15-15
  (health-check паттерн), Sprint 7 T5 R1.6 (nginx stub router).
* Feature-flag: `blue_green_deploy_enabled` (default-OFF).

## Контекст

Sprint 7 K2 DoD требует blue/green deployment в staging с возможностью
переключения трафика без даунтайма и rollback в течение ≤30 секунд.

Текущее состояние (после Sprint 7 T5 R1.6):
* `docker-compose.bluegreen.yml` подключает два независимых stack'а
  (`backend_blue` + `backend_green`) и nginx-router-stub;
* `scripts/blue_green.sh` реализует up/down/smoke/switch/rollback/status;
* nginx-router-stub читает `configs/nginx/active.conf` — заглушка,
  переключается через перезапись файла;
* нет ADR, фиксирующего deployment topology, rollback SLA, smoke gate;
* нет runbook для on-call инженеров (deploy + rollback + recovery).

## Решение

1. **Blue/Green топология двух независимых stack'ов**:
   * `backend_blue` (порт 8001) — текущая активная версия;
   * `backend_green` (порт 8002) — новая версия в прогреве;
   * nginx-router (порт 80) — единая точка входа, переключается через
     `active.conf` upstream-конфиг;
   * `db` / `redis` / `temporal` / `clickhouse` — shared между stack'ами
     (backward-совместимые схемы обязательны для miграций).

2. **Healthcheck-обязательная gating**:
   * `healthcheck.interval=10s` / `timeout=3s` / `retries=5` /
     `start_period=30s` — без здорового `/health` стек не получает трафик;
   * smoke-pipeline `./scripts/blue_green.sh smoke green` проверяет
     `/health`, `/health/db`, `/health/redis`, `/health/temporal` и
     минимальный набор reference routes (расширяется в Sprint 8).

3. **Switch / rollback SLA**:
   * `switch` — атомарный, через nginx `reload` без drop соединений
     (keepalive_timeout ≥ 30s);
   * rollback — путём `./scripts/blue_green.sh rollback`, что
     восстанавливает `active.conf` из `.blue_green.state.previous`;
   * **SLA rollback ≤ 30 секунд** (от обнаружения деградации до восстановления
     трафика на стабильный stack);
   * warm-pool: предыдущий stack НЕ останавливается сразу после switch
     (минимум 10 минут retention для быстрого rollback).

4. **Feature-flag `blue_green_deploy_enabled` (default-OFF)**:
   * по умолчанию `docker-compose.bluegreen.yml` НЕ подключается в
     `Makefile.deploy` команды;
   * при `true` — `make deploy-staging` маршрутизирует через
     `blue_green.sh up <next> → smoke → switch`;
   * default-OFF до staging-smoke + chaos-теста rollback.

5. **NGINX upstream конфиг** (`configs/nginx/active.conf`):
   * генерируется `blue_green.sh switch <target>` через template-substitution;
   * `upstream backend { server backend_<active>:8000; }` —
     один активный upstream на момент времени;
   * `keepalive 32; keepalive_timeout 30s;` — graceful переключение;
   * проверка через `nginx -t` перед `nginx -s reload`.

6. **Observability требования**:
   * каждый stack экспортит `app_version` label в метрики
     (`process_info{stack="blue|green",version="..."}`);
   * Grafana dashboard `api_latency_p95.json` фильтрует по `stack`;
   * SLO burn-rate alerts (slo_burn.yaml) обнаруживают деградацию
     с ≤5min лагом — триггер для on-call rollback.

## Последствия

### Положительные

* Zero-downtime deployment в staging/prod.
* Rollback в течение ≤30 секунд без data loss (shared БД + backward-compat миграции).
* Декларативная топология в `docker-compose.bluegreen.yml`.
* Скрипт `blue_green.sh` идемпотентен — повторные вызовы не ломают state.
* Feature-flag default-OFF — нет влияния на dev_light.

### Риски

* Shared БД требует backward-совместимых миграций (no breaking column changes).
* Warm-pool удваивает ресурсы во время deploy (memory + connections).
* nginx config-reload требует валидного active.conf — если файл сломан,
  reload падает (mitigation: `nginx -t` pre-check в скрипте).
* Stub nginx-router в R1.6 — production-grade replacement (envoy /
  production nginx с TLS+WAF) в Sprint 8 R2.
* Session-affinity нет: in-flight requests на старом stack завершаются
  через keepalive_timeout, после чего connection переключается.

## Альтернативы

* Canary deployment (10%/50%/100% rolling) — отвергнут, требует
  load-balancer с weighted upstream + per-route метриками;
  откладывается до Sprint 9 для prod.
* Recreate (stop blue → start green) — отвергнут, downtime ≥30s,
  не отвечает требованию zero-downtime.
* Feature-toggle deploy (один stack, feature-flag) — частично используется
  для бизнес-функционала, но не покрывает infrastructure/dependency upgrades.

## План внедрения

1. **Sprint 7 K2 (текущий)**:
   * расширить `docker-compose.bluegreen.yml` (healthcheck + labels +
     shared dependencies stubs);
   * создать `docs/runbooks/blue-green-rollback.md`;
   * ADR-0060 (этот документ).

2. **Sprint 7 T5 R1.6 (закрыт)**: nginx-router-stub + `blue_green.sh`
   реализованы (commit `a0a87641`).

3. **Sprint 8 R2**: production NGINX с TLS + WAF + envoy alternative;
   `active.conf` через `confd`/templating; integration с service-discovery.

4. **Sprint 9**: chaos-тест rollback (kill backend_green → автоматический
   rollback через 30s); pre-prod gate включает blue/green smoke.

## Ссылки

* PLAN.md V18.2 §S7 K2 — Blue/green compose + deploy/rollback runbook + ADR R3.1
* `docker-compose.bluegreen.yml` — топология
* `scripts/blue_green.sh` — helper-script
* `docs/runbooks/blue-green-rollback.md` — runbook on-call
* feedback_wave_a_foundation.md — entrypoint + lifespan
* https://martinfowler.com/bliki/BlueGreenDeployment.html — каноническое описание
