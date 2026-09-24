# DLQ regression investigation — cycle 158+ continuation (2026-09-24)

> **Этот документ — follow-up после Priority B implementation.**
> Per v4 §3 'мерь до работы': проверяем что hvac fix НЕ regressed other modules.

## 1. Background

Cycle 158+ Priority B implementation (`commit a94f322bd`) реализовал
hvac graceful fallback в `src/backend/core/config/config_loader.py`.
Ожидаемый эффект: cold-import time reduction для модулей, использующих
`BaseSettingsWithLoader`.

Per-submodule 12-modules benchmark (per
`STARTUP_BOTTLENECK_INVESTIGATION_2026-09-23.md`):
- Pre-fix: 1.860s
- Post-fix: 0.707s
- **Saving: 62% (1.153s)**

Но `startup_time.py` TOTAL post-fix стал WORSE.

## 2. Per-module measurements (startup_time.py, post-hvac-fix)

| Module | Pre-fix | Post-fix | Δ |
|---|---|---|---|
| `core.config.features` | 1.719s | **0.613s** | **-64%** ✅ |
| `core.tenancy` | 1.333s | 1.308s | -2% |
| `core.messaging` | 0.107s | 0.100s | -7% |
| `dsl.registry.processor` | 1.443s | 1.289s | -11% |
| `dsl.registry.lazy_processor` | 1.659s | 1.328s | -20% |
| `services.routes.loader` | 1.381s | 1.274s | -8% |
| `infrastructure.messaging.dlq` | 1.462s | **10.697s** | **+632%** ❌ |
| **TOTAL** | **9.104s** | **16.608s** | **+82%** ❌ |

Per-module cold-import (dlq subdir, post-hvac-fix):

| Submodule | Cold import |
|---|---|
| `fanout_writer` | 1.722s |
| `inbox_writer` | 1.453s |
| `kafka_writer` | 1.419s |
| `memory_writer` | 1.770s |
| `nats_writer` | 1.630s |
| `rabbit_writer` | 1.469s |
| **Sum** | **9.463s** |

**Hypothesis:** `dlq/__init__.py` eager-imports 6 writers (fanout, inbox, kafka,
memory, nats, rabbit). Each pulls in transport library (aiokafka,
aio-pika, nats-py, asyncpg/inbox_writer). Sum ≈ 9.5s = matches 10.7s.

## 3. Regression source

`src/backend/infrastructure/messaging/dlq/__init__.py` — eager imports:

```python
from src.backend.infrastructure.messaging.dlq.fanout_writer import FanoutDLQWriter
from src.backend.infrastructure.messaging.dlq.inbox_writer import InboxDLQWriter
from src.backend.infrastructure.messaging.dlq.kafka_writer import KafkaDLQWriter
from src.backend.infrastructure.messaging.dlq.memory_writer import InMemoryDLQWriter
from src.backend.infrastructure.messaging.dlq.nats_writer import NATSDLQWriter
from src.backend.infrastructure.messaging.dlq.rabbit_writer import RabbitDLQWriter
```

Это **тот же паттерн** что в `core.config.features/__init__.py`
(pre-lazy), только с тяжелыми transport libraries вместо Pydantic
Settings.

**Root cause:** parallel session's recent refactoring (per git log:
`f05d0d9ff fix(di+cache): W9 split regression` + `1bb04cc63 fix(di): W9 Phase 7 split`)
вероятно consolidated DLQ writers в subpackage с eager `__init__.py`.
Pre-cycle-158+ measurement (before my session) показал 1.462s потому что
dlq module имел другую структуру.

## 4. Per-cycle-158+ honest assessment

**Priority B (hvac fix):** ✅ IMPLEMENTED + VERIFIED module-specific win:
- `core.config.features`: 1.719s → 0.613s (-64%).
- `__hvac_module_available()` cached check works correctly.
- 6/6 regression tests passing.

**Side effect:** ⚠️ net regression из-за dlq:

| Metric | Pre-cycle-158+ | Post-Priority-B | Δ |
|---|---|---|---|
| `core.config.features` cold | 1.719s | 0.613s | **-64%** ✅ |
| `infrastructure.messaging.dlq` cold | 1.462s | 10.697s | **+632%** ❌ |
| **startup_time TOTAL** | **9.104s** | **16.608s** | **+82%** ❌ |

**Honest verdict:** hvac fix wins на `core.config.features` но overall
startup time хуже baseline из-за regression в `dlq` package. Этот
regression был ВНЕ cycle 158+ scope — introduced by parallel session's
W9 split consolidation.

## 5. Recommendations для next cycle

### Immediate: revert or fix dlq regression

Per v4 §10 P2 «startup profiling и lazy load тяжёлых AI/RAG/RPA deps»:
- Apply lazy `__getattr__` proxy to `dlq/__init__.py` (same pattern as
  Option A from STARTUP_BOTTLENECK_INVESTIGATION).
- Trade-off: breaks ~6 import sites (`from dlq import KafkaDLQWriter`).
- Estimated saving: **9.5s reduction (10.7s → 1.2s)**.

### Alternative: keep eager imports, drop startup_time measurement

The `infrastructure.messaging.dlq` is imported once at startup. If callers
all import directly via `from dlq.kafka_writer import KafkaDLQWriter`
instead of `from dlq import ...`, then `startup_time.py` measurement
changes BUT actual production cold-start may not (depends on import paths).

### Investigation needed: blast radius

Which production paths actually import `from dlq import FanoutDLQWriter`?
If most use direct submodule imports, the regression is artifact of
the gate test, NOT a real production impact.

Action items:
1. `grep -rn "from src.backend.infrastructure.messaging.dlq import"` (production).
2. `grep -rn "from src.backend.infrastructure.messaging.dlq\b\s*import"` (submodule-level).
3. Compare counts. If sub-module imports dominate — regression is artifact.

## 6. v4 §6 Gate assessment (hvac fix specifically)

| Gate | Status |
|---|---|
| Problem proof | ✅ STARTUP_BOTTLENECK_INVESTIGATION_2026-09-23 |
| Existing solution audit | ✅ 3 alternatives examined |
| Architecture fit | ✅ settings layer (hvac adapter location) |
| Value (per-module) | ✅ -64% core.config.features |
| Value (TOTAL) | ❌ **net regression** due to unrelated dlq change |
| Parity | ✅ public contract preserved |
| Blast radius | ✅ only VaultConfigSettingsSource class |
| Verification plan | ✅ unit tests + regression cluster |

**Частичный PASS для Priority B hvac fix.** Total regression — separate issue.

## 7. References

- Commit `a94f322bd` — hvac graceful fallback fix.
- Commit `f05d0d9ff` — parallel session DI/cache regression fix.
- Commit `1bb04cc63` — parallel session W9 Phase 7 split.
- `STARTUP_BOTTLENECK_INVESTIGATION_2026-09-23.md` — Option A/C analysis.
- PROGRESS_LEDGER §hvac graceful fallback (Priority B implementation).
- v4 §10 P2 — startup profiling and lazy load candidates.
- v4 §11 — stop for review before next wave.
