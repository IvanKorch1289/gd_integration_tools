# Config services bottleneck discovery (cycle 158+ continuation, 2026-09-24)

> **Этот документ — investigation finding, НЕ implementation.**
> Per v4 §11 «stop for review before next wave»: архитектурная decision —
> user direction needed.

## 1. Background

Per `STARTUP_BOTTLENECK_INVESTIGATION_2026-09-23.md` + DLQ lazy fix +
hvac fallback fix (`a94f322bd`), `aafc6218d`, current state:

```
startup_time.py TOTAL: 6.430s (pre-cycle-158+: 9.104s, -29.4%)
```

Cycle 158+ завершил Priority B Option B + Option A для конкретных modules.
Дальнейшие сavings требовали investigation других hotspots.

## 2. Re-investigation: tenancy hot-module

Prior hypothesis was что `core.logging` alone = 1.4s, causing ~1.4s overhead на
каждый tenant submodule cold import. **Этот hypothesis был НЕВЕРЕН.**

Direct cold-import test:

```bash
SEC_VAULT_ENABLED=false STRUCTLOG_CONSOLE=stderr python3.14 -c "
import time
start = time.perf_counter()
import src.backend.core.logging
print(f'core.logging alone: {time.perf_counter() - start:.3f}s')
"
# Output: 0.006s (NOT 1.4s)
```

`core.logging` already uses PEP 562 lazy `__getattr__` proxy
(per its existing docstring) — fast (~6ms) cold import.

## 3. Actual bottleneck: tenancy.quotas import chain

```
import time:    105272 |     309194 |                 src.backend.core.config.services.cache
import time:     47728 |      47728 |                 src.backend.core.config.services.graphql
import time:     52062 |      52062 |                 src.backend.core.config.services.invoker
import time:     53919 |      53919 |                 src.backend.core.config.services.jupyter_hub
import time:     46974 |      46974 |                 src.backend.core.config.services.llm
import time:     60133 |      60133 |                 src.backend.core.config.services.logging
import time:     52803 |      52803 |                 src.backend.core.config.services.mail
import time:    144665 |     144665 |                 src.backend.core.config.services.queue
import time:     51843 |      51843 |                 src.backend.core.config.services.resilience
import time:     52503 |      52503 |                 src.backend.core.config.services.rpa
```

**Total: ~550ms** для cold imports of `config.services.*` (10 of 22 submodules
в importtime summary) — без учета остальных submodules.

`config.services/__init__.py` eager imports 21 submodules. Cold import:
**1.374s** (single measurement).

## 4. Calculation: real savings potential

| Configuration | Cold import time |
|---|---|
| Current (eager 21 imports) | **1.374s** |
| Lazy Option A (PEP 562) | ~0.01s (first access) |
| Saving | **~1.36s per cold import** |

When this module is imported by 47+ files via `config_loader.py` chain,
savings ripple through весь cold-start:
- `config_loader` import cost (currently ~112ms) → reduces.
- 47 files transitive users save proportional time.
- Direct: `config.services` ~1.36s saved.
- Indirect: per-submodule additional 30-50ms saved.

**Realistic estimate**: 1.0-1.5s reduction on startup_time.py TOTAL
(down from current 6.430s → ~5.0s).

## 5. Blast-radius survey (per DLQ_REGRESSION doc recommendation)

```
direct package imports (from src.backend.core.config.services import …):
  src/backend/infrastructure/clients/external/jupyter_hub.py:10
  src/backend/core/auth/ldap_client_factory.py:100
  src/backend/core/config/settings.py:58
  tests/unit/extensions/users/test_user_service_ldap_integration.py:80, 392
  tests/unit/core/config/services/test_init.py:19
  tests/unit/core/config/services/test_outbox.py:602
  = 7 direct imports (2 production, ~5 tests)

indirect via config_loader.py: 47 files (transitive users)

total production-related touchpoints: ~10 (2 direct + 8 via config_loader.feature_flag tests)
```

Eager vs lazy risk analysis:

- 22 submodules currently eagerly loaded but most are **never accessed directly**.
- Production patterns: `from src.backend.core.config.services import Name`
  (7 sites, all use lazy-friendly names).
- Lazy proxy preserves all public symbols (`__all__`).

**Verdict**: blast-radius SMALLER than dlq fix
(dlq had 10 direct imports + 21 submodule-direct; `config.services`
has 7 direct + 47 indirect through config_loader).

## 6. Implementation pattern (suggested, per dlq precdent)

`src/backend/core/config/services/__init__.py`:

```python
"""Per-service settings singletons (PEP 562 lazy facade).

Cycle 158+ follow-up: lazy __getattr__ proxy для cold-start reduction.
Eager imports 21 submodules = 1.374s overhead; lazy ~0.01s first access.
"""

from __future__ import annotations
import importlib as _importlib
from typing import Any as _Any

# Map: submodule_name → list of public symbols from that submodule.
# Single source of truth (build _LAZY_MAP from this).
_PUBLICS = {
    "cache":      ["CacheSettings", "RedisSettings", "cache_settings", "redis_settings"],
    "graphql":    ["GraphQLSettings", "graphql_settings"],
    "invoker":    ["InvokerSettings", "invoker_settings"],
    ...
}

_LAZY_MAP: dict[str, str] = {sym: mod for mod, syms in _PUBLICS.items() for sym in syms}
_cached: dict[str, _Any] = {}

def __getattr__(name: str) -> _Any:
    if name in __all__:
        sub = _LAZY_MAP.get(name)
        if sub is None:
            raise AttributeError(...)
        module = _importlib.import_module(f".{sub}", __name__)
        value = getattr(module, name)
        _cached[name] = value
        return value
    raise AttributeError(...)

def __dir__() -> list[str]:
    return sorted(set(__all__) | set(_cached.keys()))

__all__ = (...)  # current 40+ symbols preserved.
```

## 7. Why this is NOT implemented in this session

Per v4 §11 «stop for review before next wave»:
- Cycle 158+ уже достиг 2 architectural wins (hvac + dlq lazy).
- Config services lazy fix — third architectural decision.
- Blast radius SMALLER than dlq (~10 production touchpoints vs ~30 для core.config.features Option C).
- Risk MEDIUM, manageable.

**Decision factors**:
1. **Scope risk**: Option A pattern уже proven (dlq worked); low design risk.
2. **Test coverage**: 22 submodules need individual test verification.
3. **Migration window**: 7 direct imports + 47 indirect = unique verification needed.
4. **Documentation**: ADR per cycle 158+ is heavy; inline doc rationale is enough.

**Recommended action**: implement in NEXT cycle (next user turn) с explicit
verification per v4 §6 8-gate framework. **Не** in current session because:
- 30+ commits this session is at the edge of diminishing returns per v4 §3
  «не повторять уже сделанную волну».
- Three architectural forks (hvac + dlq + config-services) in one session
  increases cognitive load для next reviewer.

## 8. Estimated post-full-Priority-B state

После implementing config.services lazy fix (next cycle):
- Pre-cycle-158+: 9.104s
- Post-cycle-158+ Options B+A: 6.430s
- Post-config-services-lazy (estimate): ~5.0s

Net savings: **~4.1s (-45% от baseline)**

Additional candidates (OPTION C, core.logging fully lazy, etc.) not
covered in this document — out of scope.

## 9. References

- `STARTUP_BOTTLENECK_INVESTIGATION_2026-09-23.md` — Option A pattern.
- `DLQ_REGRESSION_2026-09-24.md` — lazy proxy implementation pattern.
- `PROGRESS_LEDGER.md` §hvac fallback + §dlq lazy — committed fixes.
- v4 §6 8-gate audit framework для next-cycle implementation.
- v4 §10 P2 perf requirements.
