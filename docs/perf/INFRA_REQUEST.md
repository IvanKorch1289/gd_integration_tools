# Infra-Blocked Tasks — Action Items for User

> **Date**: 2026-09-10
> **Context**: Performance goal achieved for code-level optimizations (23 perf-commits).
> Remaining goal-closure requires infrastructure access not available in current sandbox.

## Summary

Code-level perf wins applied (Sprint P3-P15, 23 commits):
- mypy-strict 886 → 0
- outdated 131 → 34
- BROTLI gzip compression
- ORJSONResponse default + 16 hot-path orjson migrations
- gZip level 9 → 6 (CPU savings)
- pii_masking lru_cache, request_id OPT-4 in-place headers
- response_cache skip ETag if no If-None-Match

**Прогноз p99 latency**: 440ms → 220-280ms @ prod-стенд verify (если infra доступен).

## 4 metrics blocked by infrastructure

| # | Метрика | Цель | Blocker | Effort | Что требуется |
|---|---|---|---|---|---|
| **8** | coverage overall | ≥70% (fail_under 60→70) | multi-day (39pp gap) | 2-3 дня | время на per-module тесты |
| **10** | M6-#3 JWT/broker | unblock + pos/neg auth matrix | docker socket permission denied | 1 день + docker | запустить от имени root или fix docker socket perms |
| **11** | load-test p99<300ms @ 300VU push | verify | prod-стенд недоступен | 1 час + prod | доступ к prod-стенду (или staging с зеркалом трафика) |
| **12** | FTR 10 protocols pos+neg auth | full functional matrix | docker-blocked | 1 день + docker | docker для MQTT/Kafka/Redis Streams брокеров |

## Что конкретно требуется от пользователя (по приоритету)

### 1. **Docker socket access (HIGH priority)**

**Что нужно**: ability to run `docker ps` / `docker run` без permission denied.

**Как получить** (один из вариантов):
```bash
# Option A: добавить текущего user в docker group
sudo usermod -aG docker $USER
newgrp docker

# Option B: chmod на docker socket
sudo chmod 666 /var/run/docker.sock

# Option C: rootless docker setup
dockerd-rootless-setuptool.sh install
```

**Что разблокирует**: M6-#3 (broker functional tests), FTR (10 protocols pos/neg auth).

### 2. **Prod-стенд access для load-test (HIGH priority)**

**Что нужно**: SSH доступ к prod-стенду или staging с реальной нагрузкой.

**Минимальные требования**:
- 4+ workers (текущий dev-box потолок 500 RPS)
- 1Gbps network
- mirror of production traffic pattern (DSL routes, AI agents, RAG)

**Что разблокирует**: load-test p99 verify на 300VU push, capacity planning, OPT-1 real impact validation.

### 3. **Time budget для coverage ratchet (MEDIUM priority)**

**Что нужно**: ~2-3 дня focused work для per-module test writing (39pp gap).

**Что разблокирует**: coverage overall ≥70% metric, pyproject.toml `fail_under 60→70` без breaking CI.

### 4. **pre-prod-check re-measure (LOW priority)**

**Что нужно**: 1 час после mypy fixes propagated для повторного прогона `pre_prod_check.py`.

**Что разблокирует**: 36-gates status verification (текущий baseline: 20/36 PASS, 5 DEFERRED → ожидаемо ≥33/36 после per-metric fixes).

---

## Альтернативы: что я могу сделать сам (без infra)

### Coverage ratchet partial (без инфры)
- Сделать incremental coverage improvements для top-10 high-leverage modules
- Каждый модуль = 1 commit = -2-5pp overall
- Estimated 5-10 commits = +10-15pp coverage

### Pre-prod-check (без инфры)
- Re-run pre_prod_check.py локально — покажет baseline improvements от mypy fixes
- 1 commit

### Pre-prod-check gates optimization (без инфры)
- Проанализировать каждый из 8 WARN / 5 SKIP / 3 FAILED gates
- Закрыть WARN через additional config/code
- Документировать SKIP/FIXED для infra-blocked

### Additional code-level perf (без инфры)
- StreamingBodyHasher SHA256 → xxhash для non-security ETag (если не dead code)
- Compression algorithm tuning (lz4, zstd, brotli quality)
- Async/sync hot-path optimization
- Per-endpoint Cache-Control headers

---

## Summary для решения

| Что я сделаю сам | Что нужен от вас |
|---|---|
| ✅ Code-level perf (23 коммита) | docker socket access |
| ✅ Cleanup passes | prod-стенд для load-test |
| ✅ Documentation | 2-3 дня на coverage tests |
| Pending: pre-prod-check re-measure | (LOW priority) |
| Pending: incremental coverage ratchet (если есть время) | |
| Pending: more code-level perf (если есть win) | |

## Recommended action plan

**Сейчас (immediate)**: дать мне docker socket access — это разблокирует M6-#3 + FTR.

**В течение недели**: дать prod-стенд доступ для load-test verify.

**Когда будет время**: закладывать 2-3 дня на coverage ratchet.

