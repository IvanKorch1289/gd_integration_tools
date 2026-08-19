# Infra Health Gate — 2026-08-14 (Этап 0 ПРОВАЛЕН)

**Автор:** kimi Code CLI (cycle 206)
**HEAD:** `2532c9be`
**Протокол:** остановить работу при нестабильной инфре (per next-agent prompt §"ВАЖНО")

---

## TL;DR

**Этап 0 (Infra Health Gate) ПРОВАЛЕН.** Инфраструктура НЕ стабильна:
compose-app-1 в restart-loop (Up 17s / 30s в моих замерах, логи показывают
множественные "Starting backend" срабатывания).

**Действие**: остановить дальнейшую работу. Все 14 протоколов functional
baseline будут ложными на этой инфре.

---

## 1. Disk

```
/dev/sda2        218G         130G   78G           63% /
```

**Healthy** (63% used, 78G free). NO ENOSPC risk. Variant A repair от
13.08 (76 GB reclaimed) эффективен.

---

## 2. Docker state

```
NAME                        STATUS
compose-workflow-worker-4   Up 1h (unhealthy)
compose-workflow-worker-6   Up 1h (unhealthy)
compose-workflow-worker-7   Up 1h (unhealthy)
compose-workflow-worker-5   Up 1h (unhealthy)
compose-app-1               Up 30 seconds (was 17 seconds в test 4)
compose-postgres-1          Up 7h (healthy)
compose-redis-1             Up 7h (healthy)
compose-clamav-1            Up 22h (healthy)
tarantool-cache             Restarting (1) (8 months old, separate compose)
```

### 2.1 Postgres + Redis

**Both healthy** (7h uptime). Variant A repair от 13.08 работает:
- 26 таблиц мигрированы в `gd_integration`
- БД-уровень functional

### 2.2 compose-app-1 — НЕСТАБИЛЬНЫЙ

```
Up 17 seconds   (test 3→4 transition)
Up 30 seconds   (после test 4 retry failure)
```

Логи показывают **repeat restart pattern**:

```
13:57:42 - SQL queries executed
...
Starting backend (server=granian)...
[INFO] Starting granian (main PID: 7)
[INFO] Listening at: http://0.0.0.0:8000
[INFO] Spawning worker-1 with PID: 22
...
Starting backend (server=granian)...   ← restart
[INFO] Listening at: http://0.0.0.0:8000
[INFO] Spawning worker-1 with PID: 22
...
```

Контейнер **стартует**, **слушает** на 8000, **spawn workers**, потом
**умирает** (likely OOM или healthcheck failure) → Docker restarts.

### 2.3 Workflow workers

Все 4 worker'а `unhealthy` (Up 1h) — docker-side probe failure.
Per SYNTHESIS_2026-08-13 §6 (Variant A repair): пробы :9100 = 200,
но docker-side HEALTHCHECK помечает их unhealthy из-за старого
Dockerfile (общий HEALTHCHECK → worker'ы не подходят).

Dockerfile fix был сделан (см. `ops/compose/Dockerfile` modified files),
но **image не пересобран**.

### 2.4 Tarantool

Отдельный compose (`docker-compose.yml` НЕ включает tarantool).
`Restarting (1) 2 seconds ago` — продолжает crash-loop (8 months old).
Не критично для основного функционала.

---

## 3. Curl /health stability test (5 calls × 20s interval)

| Test | Time | HTTP Code | Duration | Status |
|---|---|---|---|---|
| 1 | T+0s | 200 | 10 ms | OK |
| 2 | T+20s | 200 | 8 ms | OK |
| 3 | T+40s | 200 | 6 ms | OK |
| 4 | T+60s | **000** (connection reset) | 1 ms | **FAIL** |
| 4 retry | T+65s | **000** (connection reset) | 0.5 ms | **FAIL** |
| 5 | T+85s | (skipped, infra unstable) | — | **SKIP** |

**Result**: 3/5 first-pass OK, но test 4 упал → **infrastructure
НЕ stable**. Per протоколу — остановить работу.

---

## 4. Root cause hypothesis

`compose-app-1` в restart-loop:
- granian workers (PID 22, 24, 26, 28) spawn при старте
- worker'ы падают после первой нагрузки (likely OOM-killed или
  segfault из-за старого image с битым gRPC reference)
- docker перезапускает контейнер
- цикл повторяется каждые ~30-60 секунд

**Verification**: docker logs показывают "Starting backend" 3+ раз за
последние 60 секунд.

---

## 5. Action items (требует решения пользователя)

### 5.1 Critical (blocker)

- [ ] **Hard restart `compose-app-1`** для подтверждения причины:
      ```bash
      sudo docker restart compose-app-1
      ```
      Если после restart стабильно Up > 5 мин — инфра здорова.

- [ ] **Rebuild image** (если restart не помогает):
      ```bash
      sudo docker build -f ops/compose/Dockerfile -t gd-integration-tools:light .
      sudo docker compose -f ops/compose/docker-compose.yml up -d --force-recreate app
      ```

- [ ] **Cycle 205 NEW-2 fix deploy**: `compose-app-1` использует cached
      image. После `docker build` нужно `compose up -d --force-recreate`
      чтобы активировать body-parser fix.

### 5.2 Important (not blocker)

- [ ] **Workflow workers**: после image rebuild — worker'ы должны
      стать healthy (docker-side probe :9100 = 200).

- [ ] **Tarantool**: 8-month-old crash-loop. Если не критично для
      workflow — оставить; иначе investigate logs.

---

## 6. Что НЕ сделано (Этап 0 провален)

Per протоколу:

- Этап 1 (Functional Baseline 14 протоколов) — **отменён**
- Этап 2 (Fact-check) — **отменён**
- Этап 3 (Frontend → facade миграция) — **отменён**
- Этап 4 (Regression) — **отменён**
- Этап 5 (Final report) — **отменён**

**Рекомендация**: пользователь/оператор должен решить инфраструктурную
проблему (restart/rebuild compose-app-1), затем re-run Этап 0.

---

## 7. Артефакты

- `docs/audit/INFRA_HEALTH_2026-08-14.md` (this file)
- HEAD unchanged: `2532c9be`
