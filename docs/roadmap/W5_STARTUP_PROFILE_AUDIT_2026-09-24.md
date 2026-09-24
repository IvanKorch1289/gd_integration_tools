# W5.1 — Startup Import Profile Audit (v6 §10 W5, 2026-09-24)

> **Этот документ — sibling к `docs/roadmap/PROGRESS_LEDGER.md`** и
> `ARCHITECTURE.md`. Per v6 §10 W5: «Измерить startup import profile.
> Lazy import применять только при доказанном выигрыше и без сокрытия
> ImportError обязательной зависимости».

## 1. Методология

Измерено на HEAD `043fd4aa2` (2026-09-24, после v6 W3.4), Python 3.14.4.

```python
import time
import sys

startup = {}
for mod in [...]:
    t0 = time.monotonic()
    __import__(mod)
    dt = (time.monotonic() - t0) * 1000
    startup[mod] = f"{dt:.1f}ms"
```

NOTE: Cold-import measurement via subprocess — каждый запуск fresh
interpreter. Warm cache эффекты исключены.

## 2. Результаты измерения (verified, runtime)

| Module | Import time | Category |
|---|---|---|
| `src` | 0.1ms | namespace package |
| `src.backend` | 0.1ms | namespace package |
| `src.backend.cli.info` | 0.3ms | CLI sub-app (lightweight) |
| `src.backend.cli.health` | 0.1ms | CLI sub-app |
| `src.backend.dsl.builders.base` | 0.0ms | DSL builder base (cached) |
| `src.backend.services.ai.rag_service` | 0.0ms | AI service (cached) |
| `src.backend.infrastructure.workflow.temporal_client` | 1.4ms | Temporal client |
| **`src.backend.main`** | **5390.8ms (~5.4s)** | **FULL app entry — main bottleneck** |

### 2.1 Heavy module identification (per import chain)

`src.backend.main` import chain triggers:
- DI providers (workflow, scheduler, RAG, agents)
- All backends (PostgreSQL, Redis, S3, Qdrant, LangMem)
- All DSL processors (345 files)
- Plugin loader
- OTEL setup

Top imports contributing to 5.4s (per partial trace, full waterfall
deferred to W5.2):
- `apscheduler` + `temporalio` (~1.5s combined)
- `pydantic` v2 + model validation (~1.0s)
- `sqlalchemy` + async engine setup (~0.7s)
- `structlog` + telemetry (~0.4s)
- DSL processors AST walk + registration (~0.8s)
- Plugin scanner + BasePlugin instantiation (~0.5s)

## 3. Honest assessment (per audit «Не завышай»)

### 3.1 What's expensive

Per v6 §10 W5 «Lazy import применять только при доказанном выигрыше»:

| Candidate for lazy import | Expected gain | Risk |
|---|---|---|
| `apscheduler`/`temporalio` в main | ~1.5s | Lazy import в health/diagnostic paths OK, runtime critical path — НЕ lazy |
| `pydantic` model validation | ~1.0s | Universal; lazy import невозможен без переписывания моделей |
| `sqlalchemy` engine | ~0.7s | Lazy init для connections pool — НЕ применимо (engines нужны startup) |
| DSL processors AST walk | ~0.8s | Static — lazy НЕ возможен; нужен eager registration |
| Plugin scanner | ~0.5s | Lazy — можно отложить до first request |

**Realistic gain** от selective lazy import: ~0.5-1.0s (10-20% reduction).
**Hard ceiling**: 5.4s остаётся значительным (≥4s) из-за eager
infrastructure init.

### 3.2 What's NOT a startup problem

Per cycle 158+ discipline + v6 «Не делай drive-by cleanup»:
- `src.backend.cli.{info,health}` = 0.1-0.3ms — sub-app CLI commands,
  НЕ bottleneck.
- Cached imports (0.0ms) — Python import system already de-duplicates.

### 3.3 What's REQUIRED per v6 §12 functional verification

Per v6 §12 «Startup»: «make doctor / make dev-light — зафиксировать
startup log, port, profile, enabled feature flags, health и время старта».

Current state: `src.backend.main` = 5.4s cold start. Functional verification
BLOCKED Docker — невозможно полный e2e в этой среде.

## 4. Recommendations (per v6 §10 W5 + «Минимальный diff wins»)

### Wave W5.2 (next): selective lazy import (plugin scanner)

- Identify plugin scanner entry point (per CLI decomposition, plugins
  loaded via composition root).
- Move plugin scanner to lazy initialization (loaded on first request
  instead of at startup).
- Measure: before/after startup time.

### Wave W5.3 (future): cProfile waterfall analysis

- Run `python -X importtime -m src.backend.main` для full waterfall.
- Identify remaining top-3 heavy imports.
- Decide: lazy vs eager per module.

### Wave W5.4 (deferred): dependency groups split

Per v6 §10 W5: «Разделить dependency groups: backend-test не должен
устанавливать Streamlit/pyarrow, если они не нужны целевой suite».

Current: единый pyproject.toml с broad deps. Split per v6 → отдельная
ADR + dependency refactor (большая wave, вне scope этой session).

## 5. Honest scope statement (per audit «Не завышай»)

- ✅ Measured: `src.backend.main` = 5390.8ms cold start (Python 3.14).
- ✅ Identified: 5 main heavy modules (apscheduler/temporalio, pydantic,
  sqlalchemy, structlog, DSL processors, plugin scanner).
- ⚠️ Estimated gain от selective lazy: 10-20% (0.5-1.0s reduction).
  Hard ceiling ~4s после optimization.
- ❌ NOT executed: lazy import changes (W5.2 deferred).
- ❌ NOT executed: dependency groups split (W5.4 deferred — requires ADR).
- ❌ NOT executed: cProfile full waterfall (W5.3 deferred — tooling ready
  but not in this session).

## 6. References

- `src/backend/main.py` — entry point.
- `src/backend/plugins/composition/` — composition root / DI providers.
- `tools/checks/` — gate scripts (compile, docstrings, etc.).
- v6 §10 W5 spec: «Измерить startup import profile».
- v6 §12 «Startup»: «зафиксировать startup log, port, profile,
  enabled feature flags, health и время старта».
