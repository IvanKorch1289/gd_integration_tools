# Extension DI Infrastructure-Module Registry (S172 M3 — ARC-006)

**Status**: SHIPPED 2026-06-30. **Breaking change**: нет (additive only).

## TL;DR

Расширения (`extensions/<name>/`) теперь могут **регистрировать** свой
infrastructure-модуль в core DI registry через публичный SDK API.
Раньше `core/di/module_registry.INFRA_MODULES` был static dict,
только `core`-developers мог расширять. M3 вводит extension-safe
registry с path-prefix validation.

## Архитектура

```
┌─────────────────────────────────────────────────────────────────────┐
│ Extension plugin.py (on_load hook)                                  │
│   from src.backend.sdk import register_infra_module                  │
│   register_infra_module("my_ext.metrics",                           │
│                          "extensions.my_ext.infrastructure.metrics") │
└─────────────────────────────────────────────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────────────┐
│ src/backend/sdk/__init__.py                                          │
│   __getattr__("register_infra_module") →                            │
│     src.backend.core.di.module_registry.register_extension_module   │
└─────────────────────────────────────────────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────────────┐
│ core/di/module_registry_extensions.py (S172 M3 NEW)                 │
│   • is_extension_path() — path-prefix validation                    │
│   • register_extension_module(key, dotted_path) → bool              │
│   • unregister_extension_module(key) → bool                         │
│   • clear_extension_modules() → int                                 │
│   • list_extension_modules() → dict[str, str]                       │
│   • Thread-safe via threading.Lock                                 │
└─────────────────────────────────────────────────────────────────────┘
                                │
                                ▼
┌─────────────────────────────────────────────────────────────────────┐
│ core/di/module_registry.py:resolve_module(key) — UPDATED (S172 M3)  │
│   Resolution order:                                                 │
│     1. Extension-registry (lookup first → extension wins over core) │
│     2. Static INFRA_MODULES                                         │
│     3. ModuleRegistryError(если missing)                             │
└─────────────────────────────────────────────────────────────────────┘
```

## Files

| Path | LOC | Purpose |
|---|---|---|
| `src/backend/core/di/module_registry_extensions.py` | 215 (NEW) | Extension-safe registry |
| `src/backend/core/di/module_registry.py` | +30 | `resolve_module` integration |
| `src/backend/sdk/__init__.py` | +25 | Public SDK facade (`register_infra_module`, etc.) |
| `tests/unit/core/di/test_extension_registry.py` | 270 (NEW) | Unit tests |

## API

### Public SDK surface (`src.backend.sdk`)

```python
from src.backend.sdk import (
    register_infra_module,        # register an extension module
    unregister_infra_module,      # unregister by key
    ExtensionRegistrationError,   # raised on validation failure
    is_extension_path,            # bool check — True если path valid
)
```

```python
# Typical usage in extensions/<name>/plugin.py:

def on_load() -> None:
    register_infra_module(
        "my_ext.metrics",
        "extensions.my_ext.infrastructure.metrics",
    )

def on_unload() -> None:
    unregister_infra_module("my_ext.metrics")
```

### Validation rules

* `key` — non-empty `str`.
* `dotted_path` — MUST:
  * Начинаться с `extensions.` prefix.
  * Содержать только `[a-z0-9._]` characters (no hyphen / space / uppercase).
  * Not contain `..` (path-traversal protection).
  * Not end with `.`.
  * Длина ≤ 200 chars.

Любое нарушение → `ExtensionRegistrationError`.

### Thread safety

* `register_extension_module` / `unregister_extension_module` /
  `clear_extension_modules` используют `threading.Lock`.
* Можно вызывать из `asyncio` tasks — non-async path (registry I/O
  is pure Python dict ops, sub-millisecond).

### Lifecycle

| Event | Action |
|---|---|
| Plugin install | `BasePlugin.on_load()` → `register_infra_module()` |
| App startup | `lifespan` orchestrator calls `on_load` for each plugin |
| App shutdown | `lifespan` → `on_unload()` for each plugin → `unregister_infra_module()` |
| Test fixture | `pytest.fixture(autouse=True) def _reset(): clear_extension_modules()` |

## Resolution priority (EXTENSION WINS over CORE)

```python
# core/di/module_registry.py:resolve_module()
if key in list_extension_modules():
    # Extension-registered → import via sys.modules cache (SINGLETON)
    return importlib.import_module(dotted_path)
elif key in INFRA_MODULES:
    # Core-static → scope-aware (SINGLETON/SCOPED/TRANSIENT)
    return _resolve_singleton(key) if SINGLETON else ...
else:
    raise ModuleRegistryError(...)
```

**Почему extension wins**: core-INFRA_MODULES pre-defined;
extensions add NEW keys (не сlobber'ят core). Проверка is done
через простой membership-test в extension dict, который hot-path
O(1) для extension-плагинов.

## Security properties

### Threat model
* **Malicious extension пытается зарегистрировать core-prefix'нутый модуль**.
  * Защита: `is_extension_path` enforces `extensions.` prefix.
  * При попытке register `src.backend.core.foo` → `ExtensionRegistrationError`.
* **Path-traversal via `..`**.
  * Защита: `".." in dotted_path → False`.
* **Race condition при concurrent register из multiple threads**.
  * Защита: `threading.Lock` обертывает все mutation ops.
* **Превышение length DoS**.
  * Защита: `_MAX_DOTTED_PATH_LENGTH = 200`.

### Audit trail

Каждый successful register / unregister / clear логируется
через `src.backend.core.logging.get_logger` (structlog streaming).
Migration audit-events расширяются через `M2.3 audit-event pattern`.

## Backward compatibility

| Caller | Pre-M3 | Post-M3 |
|---|---|---|
| `resolve_module("clients.storage.redis")` | INFRA_MODULES lookup | INFRA_MODULES lookup (unchanged for non-extension keys) |
| `resolve_module("ext.foo")` | `ModuleRegistryError` | Imports `extensions.ext.foo` if registered |
| Extension calling `register_infra_module` | N/A (no API existed) | New API available |

Никаких breaking changes — добавлен новый public API, всё backward-compat.

## Testing

```bash
uv run pytest tests/unit/core/di/test_extension_registry.py -q
# 40 passed.

uv run pytest tests/unit/core/di tests/unit/core/auth tests/unit/integration -q
# 407 passed + 1 skipped (test_app_state pre-existing baseline).
```

## Extension SDK surface (after M3)

The full public API surface for extensions now includes:

| Symbol | Purpose |
|---|---|
| `Exchange`, `Pipeline` | DSL engine primitives |
| `get_service`, `register_factory` | DI runtime services |
| `register_infra_module` | **NEW (M3 ARC-006)** Infrastructure-module DI |
| `unregister_infra_module` | **NEW (M3 ARC-006)** |
| `ExtensionRegistrationError` | **NEW (M3 ARC-006)** |
| `is_extension_path` | **NEW (M3 ARC-006)** |
| `app_state_singleton` | FastAPI app state decorator |
| `BaseError` | Root error class |
| `Clock` | Monotonic time |
| `run_hub_notebook`, `NotebookSpec`, `NotebookRegistry` | Jupyter Hub |
| `AgentToolPolicy` | AI tool policy |

Extensions MUST import only from this surface (per AGENTS.md rule).

## References

* Plan file: `.mimocode/plans/1782802381991-proud-garden.md`
* Audit: `docs/audit/AUDIT_2026-06-30.md`
* Argon2id migration (predecessor): `docs/security/argon2id_migration.md`
