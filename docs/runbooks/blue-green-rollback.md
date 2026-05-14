# Runbook — Blue/Green deploy + rollback

> **Цель**: безопасное переключение production-трафика между двумя
> stack'ами (blue ↔ green) с rollback ≤30 секунд при деградации.
>
> **Применяется к**: staging + prod.
>
> **Связано**: ADR-0060, `docker-compose.bluegreen.yml`, `scripts/blue_green.sh`,
> Grafana dashboard `slo_burn_rate.json`, alerts `slo_burn.yaml`.

---

## 1. Предусловия

Перед началом deploy убедиться:

1. **Health-checks**: `curl -fsS http://blue/health` и
   `curl -fsS http://green/health` (если green уже запущен) возвращают `200`.
2. **Feature-flag**: `blue_green_deploy_enabled=true` в целевом env.
3. **Backward-совместимая миграция БД**: новая версия green не ломает
   схему для blue (additive-only changes — нет DROP/RENAME колонок).
4. **Resilience snapshot**: dashboard `resilience_snapshot.json` показывает
   все circuit-breakers / rate-limiters / bulkheads в `closed` / `available`.
5. **Active stack известен**: `./scripts/blue_green.sh status` → `active stack: blue`.

---

## 2. Deploy procedure (blue → green)

### Шаг 1. Подготовка green

```bash
export GREEN_TAG="v2.31.0"          # новая версия
./scripts/blue_green.sh up green     # docker compose up backend_green
```

Ожидается:
* контейнер `backend_green` в статусе `healthy` (через ≤60s);
* `/health` отвечает `200`;
* логи без `ERROR` / `CRITICAL` в первые 30 секунд.

### Шаг 2. Smoke-test против green

```bash
./scripts/blue_green.sh smoke green
```

Расширенный smoke (рекомендуется для prod):

```bash
# 5 эталонных запросов
for endpoint in /health /health/db /health/redis /health/temporal /api/v1/system/info; do
    curl -fsS --max-time 5 "http://localhost:8002${endpoint}" || exit 1
done
```

При **fail** — НЕ переключать. Зафиксировать ошибку, остановить green,
открыть инцидент.

### Шаг 3. Переключение router

```bash
./scripts/blue_green.sh switch green
```

Что происходит:
* `active.conf` перезаписывается: `upstream backend { server backend_green:8000; }`;
* `nginx -t` валидирует конфиг;
* `nginx -s reload` — graceful reload (in-flight requests завершаются на blue);
* `.blue_green.state` обновляется на `green`;
* `.blue_green.state.previous` сохраняет `blue` (для rollback).

### Шаг 4. Мониторинг 5-15 минут

Открыть Grafana dashboards:
* `slo_burn_rate.json` — burn-rate alerts MUST stay green;
* `api_latency_p95.json` — p95 в пределах ±20% от baseline;
* `db_pool_health.json` — нет всплеска `pool_wait_time`;
* `resilience_snapshot.json` — нет новых открытых circuit-breakers.

Если в течение 15 минут метрики стабильны → перейти к шагу 5.

### Шаг 5. Останов старого stack (warm-pool retention)

**Минимум 10 минут после switch** перед остановкой blue:

```bash
sleep 600                                 # warm-pool retention
./scripts/blue_green.sh down blue        # остановить старый stack
```

---

## 3. Rollback procedure (green → blue)

### Триггеры для rollback

* `slo_burn_rate` alert: `error_budget_burning_fast` сработал (1h burn ≥ 14.4×);
* `api_latency_p95` > baseline × 1.5 в течение 5+ минут;
* > 1% 5xx-ответов на reference endpoints;
* on-call инженер обнаружил критический баг или регрессию.

### Команда rollback

```bash
./scripts/blue_green.sh rollback
```

Что происходит:
* `active.conf` перезаписывается: `upstream backend { server backend_blue:8000; }`;
* `nginx -s reload` (≤2s);
* `.blue_green.state` восстанавливается на `blue`;
* трафик переключается обратно на стабильный stack.

**SLA**: trip → restored ≤ 30 секунд.

### Если warm-pool остановлен (blue уже остановлен)

```bash
./scripts/blue_green.sh up blue              # поднять blue из последнего image-tag
./scripts/blue_green.sh smoke blue           # smoke
./scripts/blue_green.sh switch blue          # переключить
```

В этом случае SLA расширяется до ≤2 минут (зависит от времени старта
контейнера + health-check).

---

## 4. Recovery от сломанного active.conf

Если `nginx -t` падает (повреждённый template или невалидный upstream):

```bash
# Восстановить из backup
cp configs/nginx/active.conf.backup configs/nginx/active.conf
docker exec nginx_router nginx -t
docker exec nginx_router nginx -s reload
```

Если backup отсутствует:

```bash
cat > configs/nginx/active.conf <<'EOF'
upstream backend {
    server backend_blue:8000;
    keepalive 32;
}
server {
    listen 80;
    location / {
        proxy_pass http://backend;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        keepalive_timeout 30s;
    }
}
EOF
docker exec nginx_router nginx -t
docker exec nginx_router nginx -s reload
```

---

## 5. Post-incident проверка

После rollback и стабилизации:

1. **Archive logs**: `docker logs backend_green > /var/log/green-incident-$(date +%F).log`.
2. **Capture metrics**: экспорт Grafana panels за период инцидента (PNG + CSV).
3. **Open postmortem**: заполнить `vault/postmortem-<date>-<slug>.md`
   по шаблону (timeline, root cause, mitigation, action items).
4. **Update tests**: добавить regression-тест на обнаруженный баг (если
   возможно воспроизвести).
5. **Schedule rerun**: новая попытка deploy — после fix и валидации в dev_light.

---

## 6. Известные подводные камни

| Симптом | Причина | Mitigation |
|---|---|---|
| `nginx -s reload` зависает | keep-alive соединения не закрываются | `proxy_read_timeout 30s;` ограничивает |
| Smoke OK, но prod 5xx | разница между smoke endpoints и реальной нагрузкой | расширить smoke на top-10 routes по RPS |
| Rollback не помог | shared cache содержит invalid data (Redis) | `redis-cli FLUSHDB` (или per-tenant invalidation) |
| Двойной trigger rollback | flapping alert (1h burn ≈ 14.4x) | повысить порог alert до 14.4× + 5min duration |
| green не стартует | новая migration ломает blue | rollback миграции или forward-fix migration |
| Active.conf поломан | bad template-substitution | backup automate перед switch (R1.6 TODO) |

---

## 7. Контакты

* **Owner team**: K2 Resilience+Perf (Sprint 7)
* **Escalation**: on-call dev → tech-lead → infrastructure-team
* **Related runbooks**: `docs/runbooks/http3-server.md`

---

**Версия runbook**: 1.0 (2026-05-14, Sprint 7 K2)
**Связанный ADR**: ADR-0060 (Blue/Green deployment topology)
