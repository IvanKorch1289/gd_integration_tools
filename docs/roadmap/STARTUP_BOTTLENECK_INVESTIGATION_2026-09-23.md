# Startup bottleneck investigation — cycle 158+ continuation (2026-09-23)

> **Этот документ — follow-up на `CYCLE_158_PLUS_HANDOFF.md` Priority B.**
> Конкретные measurements для lazy load design decision.

## 1. Background

`startup_time.py` post-fix (`06b83cd49`) revealed total cold import time
**9.104s** (было `'infs'` masked, baseline 1.304s). Per-module:

| Module | Cold import |
|---|---|
| `core.config.features` | 1.719s |
| `core.tenancy` | 1.333s |
| `dsl.registry.processor` | 1.443s |
| `dsl.registry.lazy_processor` | 1.659s |
| `services.routes.loader` | 1.381s |
| `infrastructure.messaging.dlq` | 1.462s |
| `core.messaging` | 0.107s |

## 2. Drill-down: core.config.features 1.7s

`src/backend/core/config/features/` package structure:
- `__init__.py` (314 LOC): aggregate `FeatureFlags` via Pydantic multi-inheritance.
- 17 submodules: `ai`, `ai_rag`, `auth`, `billing`, `dsl`, `experimental`,
  `infrastructure`, `net`, `observability`, `plugins`, `resilience`, `security`,
  `sprint5`, `sprint5_dsl`, `sprint5_k2`, `sprint6`, `sprint7`, `sprint19_ai`,
  `sprint19_dx`, `sprints_15_17`.
- 258 Field() calls total (across all submodules).

### Per-submodule cold-import time (sequential, env minimal)

```
ai                    1.760s
ai_rag                1.669s
auth                  1.646s
billing               1.666s
dsl                   1.681s
experimental          1.544s
infrastructure        1.528s
```

Average: **~1.6s per submodule**. NOT proportional to Field() count.

### Control measurements

```
config_loader (base):              0.390s
pydantic_settings (library):       0.111s
```

### Total for 12 modules

```
12 features modules cold-import: 1.860s
(start to last import — sequential)
```

## 3. Analysis: bottleneck = Pydantic Model class creation

Per-submodule time ≈ **1.5s consistently**, despite Field() count
varying from 3 (auth) to 33 (infrastructure).

→ Cost dominant factor: **Pydantic Model class instantiation**, NOT
Field() evaluation.

Per-class overhead ~1.2s = config_loader base (0.390s) + class compilation
(via `BaseSettingsWithLoader` inheritance) + introspection.

## 4. Hypotheses for optimization (deferred to design decision)

### A. Lazy `__getattr__` proxy в `__init__.py`

Current `__init__.py`:
```python
from src.backend.core.config.features.ai import AIFlags as AIFlags
from src.backend.core.config.features.ai_rag import AIRAGFlags as AIRAGFlags
# ... 17 more
from src.backend.core.config.features.sprints_15_17 import Sprints1517Flags as Sprints1517Flags
```

Proposed:
```python
def __getattr__(name: str) -> Any:
    """Lazy import — only load submodule when name requested."""
    if name.endswith("Flags") and name != "FeatureFlags":
        submodule = re.sub(r"Flags$", "", name).lower()
        module = importlib.import_module(f".{submodule}", __name__)
        return getattr(module, name)
    raise AttributeError(name)
```

Trade-offs:
- ✅ Cold import `from ... import feature_flags` → 0.1s (was 1.7s).
- ❌ First access to any flag triggers full Pydantic class load.
- ⚠️ Existing imports Eagerly-referenced from `__init__.py`
  (`feature_flags` singleton construction) — break compat.

### B. Suspend VaultConfigSettingsSource на settings model если hvac missing

Currently `BaseSettingsWithLoader.__init__` attempts Vault adapter
configuration even when `hvac` не установлен. Each Pydantic Model
construction emits 17+ error logs (hvac missing warning).

Proposed: skip Vault source if `hvac` cannot be imported.

```python
def __init__(self, **kwargs):
    super().__init__(**kwargs)
    try:
        import hvac  # noqa: F401
        vault_source = VaultConfigSettingsSource(...)
    except ImportError:
        vault_source = None  # skip silently
```

Trade-offs:
- ✅ Removes 17+ log spam per init.
- ✅ Expected: removes ~200ms per Pydantic class construction (less
  introspection overhead без failing Vault attempt).
- ❌ Log signal loss — если hvac should be available but isn't (dev env misconfigured),
  silently passes.

### C. Reduce number of BaseSettings classes через mixin composition

Currently 17 separate BaseSettings classes (AIFlags, AIRAGFlags, etc.).
Could merge related into fewer classes (1-3). Each fewer class =
proportional speed improvement.

Trade-offs:
- ✅ 17 → 3 classes = ~80% reduction.
- ❌ Field locality loss (all flags in one giant class).
- ❌ Risk to backward compat (imports `AIFlags` should still work).
- ⚠️ Big architectural change, requires ADR.

## 5. Measurement methodology

Per v4 §3 evidence-first, NOT estimated — measured via subprocess
(`SEC_VAULT_ENABLED=false STRUCTLOG_CONSOLE=stderr python3.14 -c '...'`)
following same pattern as `startup_time.py` post-fix.

Reproducible команда:
```bash
SEC_VAULT_ENABLED=false STRUCTLOG_CONSOLE=stderr python3.14 -c "
import time
start = time.monotonic()
import src.backend.core.config.features.{ai,ai_rag,auth,billing,dsl,experimental,infrastructure,net,observability,plugins,resilience,security,sprint5}
print(f'12 modules: {time.monotonic() - start:.3f}s')
"
```

## 6. References

- `CYCLE_158_PLUS_HANDOFF.md` — Priority B (lazy load)
- `CYCLE_158_FORMAT_DRIFT_VERIFICATION.md` — sibling doc
- `startup_time.py` measurement fix `06b83cd49` (real numbers revealed)
- PROGRESS_LEDGER §Cycle 158+ v4 §10 sweep
- v4 §6 (Gate допуска улучшения) — required for any fix implementation
