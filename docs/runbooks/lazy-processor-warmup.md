# Runbook: Lazy processor warmup

> Owner: K3.

## Symptom

* Startup time > 3s (см. `tools/checks/startup_time.py` failed).
* Первый request на каждый процессор показывает high latency (lazy load).
* Memory profiling: пиковая RAM не растёт пропорционально количеству
  активных routes.

## Detection

```bash
.venv/bin/python tools/checks/startup_time.py
# FAILED 2 modules exceed 3.0s
# src.backend.dsl.engine.processors.ai: 4.2s
# src.backend.dsl.engine.processors.eip.routing: 3.8s
```

## Diagnosis

`LazyProcessorRegistry` (K3 W3) импортирует процессоры через
`importlib.import_module` только при первом lookup. Если в startup'е
тяжёлые модули импортируются eagerly — нарушение принципа.

```bash
grep -rn "from src.backend.dsl.engine.processors import" src/backend/ | head -20
```

Каждая такая строка — потенциальный eager import.

## Mitigation

### Option A: convert eager → lazy
```python
# Было:
from src.backend.dsl.engine.processors.ai import LLMCallProcessor

# Стало:
from src.backend.dsl.registry.lazy_processor import LazyProcessorRegistry

lazy = LazyProcessorRegistry(base=registry)
lazy.register_lazy(
    name="llm_call",
    namespace="core",
    module_path="src.backend.dsl.engine.processors.ai:LLMCallProcessor",
)
# Импорт случится при первом resolve("core:llm_call").
```

### Option B: warmup at deploy time
```python
# В lifespan:
if not feature_flags.lazy_processor_loading:
    # Eager mode (default до S10): resolve all
    lazy.resolve_all()
```

### Option C: capability-only access
Если процессор используется только для capability check (без exec) —
`lazy.capabilities_for(fqn)` не делает import.

## Verification

* `startup_time.py` → OK (< 3s per module).
* p99 first-request latency для каждого route < +100ms vs warm.
* RAM startup baseline снизился (cold = lazy).

## Trade-offs

| Mode | Startup | First-request | RAM |
|---|---|---|---|
| Eager (legacy) | slow (10s) | fast | high |
| Lazy (default) | fast (2s) | slow (+ms) | low |
| Lazy + resolve_all on idle | fast | fast (после idle) | high |

## Tooling

```bash
make startup-time         # daily gate
make startup-profile      # py-spy flamegraph
```
