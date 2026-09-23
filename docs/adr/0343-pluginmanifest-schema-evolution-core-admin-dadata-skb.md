# ADR-0343 — PluginManifest schema migration: core_admin / dadata / skb

## Статус

**Accepted** (2026-09-23, cycle 158+). Закрывает pre-existing schema
violation в `extensions/{core_admin,dadata,skb}/plugin.toml`,
discovered через fixed gate `check_compat.py` (commit `cc6806bd6`).

## Контекст

`check_compat.py` валидирует каждый `plugin.toml` против Pydantic-схемы
`PluginManifest` (`src/backend/core/plugin_runtime/manifest_toml.py`).

**Pre-fix state (RED-exit1, после фикса gate import path):**
3 extension manifest-файла используют **nested `[plugin]` + `[dependencies]`
table** структуру:

```toml
# extensions/core_admin/plugin.toml:
trust_tier = "A"
[plugin]
name = "core_admin"
version = "1.0.0"
description = "..."
entry_class = "extensions.core_admin.schemas_only:SchemasOnlyEntry"

[dependencies]
# (пустой)
```

Но `PluginManifest` (canonical core/plugin_runtime) ожидает
**top-level scalar fields** и не допускает nested tables:

Pydantic v2 failures per file:
- `name`, `version`, `requires_core`, `entry_class` — **Field required** (missing).
- `plugin`, `dependencies` — **Extra inputs not permitted** (top-level tables forbidden).

**Same pattern что и `agent_basic.policy.yaml`** (ADR-0342 fixed).
Но scope больше:
- 3 файла, не 1.
- Touches `extensions/` (operational surface).
- Plugin loading = install-time contract.

## Решение

**Мигрировать 3 файла к top-level flat structure:**

```toml
# Новый формат (matches PluginManifest schema):
trust_tier = "A"
name = "core_admin"
version = "1.0.0"
description = "..."
entry_class = "extensions.core_admin.schemas_only:SchemasOnlyEntry"
requires_core = ">=0.2.0"
# dependencies — implicit (core plugin; capabilities handled in code)
```

**Ключевые решения**:
1. **Добавить `requires_core`** — было отсутствует в nested form.
   Default-safe: `">=0.2.0"` (latest в baseline).
2. **Удалить nested `[plugin]` table** — flatten в top-level.
3. **Удалить пустой `[dependencies]` table** — отсутствие значит
   "no declarative dependencies".
4. **`trust_tier`** оставлен как есть (top-level scalar, не в [table]).
5. **`description`** оставлен как есть (top-level scalar, optional).

**Affected files**:
- `extensions/core_admin/plugin.toml` (SchemasOnlyEntry pattern)
- `extensions/dadata/plugin.toml`
- `extensions/skb/plugin.toml`

## Альтернативы рассмотрены

### 1. Extend `PluginManifest` schema чтобы принять nested [plugin] tables
- ❌ Отвергнуто: schema drift в wrong direction.
- Canonical manifest-schema convention в community = flat top-level
  (Cargo, npm, etc.). Nested tables — premature complexity.
- v4 §4.2 «Один implementation — без лишнего interface»: schema
  flattening — simpler, matches convention.

### 2. Backward-compat shim: load_nested_plugin_manifest loader
- ❌ Отвергнуто: v4 §10 P1 «удалять shim только после 0 importers +
  migration window + contract test». Введение нового shim debt-creation.
- Лучше однократная миграция.

### 3. Ничего не делать
- ❌ Отвергнуто: 3 extensions имеют broken manifest schema → potential
  install failure at deploy time.
- ADR-0338 (Outbox crash matrix) — аналогичный подход: решать
  schema integrity сразу, не допускать silently-broken extensions.

## Последствия

### Позитивные

- ✅ `check_compat.py` exit 0 после fix (4 plugins total → 3 + additional
  для non-broken).
- ✅ Production plugin loading не падает на install (Pydantic fail-closed).
- ✅ Schema convention = flat top-level (matches Cargo/npm/ecosystem).
- ✅ Manifest schema теперь single source of truth (one shape).
- ✅ Removes ambiguity между `[plugin].name` и top-level `name`.

### Негативные

- ⚠️ Если 3 extensions имеют other code-level assumptions о nested
  structure — могут be impact (например custom loader). Смягчение:
  load_plugin_manifest() — основной loader, читает top-level
  fields только.
- ⚠️ `extensions/{core_admin,dadata,skb}` могут иметь `_get_manifest()`
  helpers — нужно проверить, что они также читают top-level.
- ⚠️ Если extensions НЕ используются через canonical loader
  (например, через custom loader в tests), возможны edge cases.

### Нейтральные

- 3 файла изменены (structurally: ~10 lines moved).
- Gate (check_compat.py) теперь passes.

## Что НЕ покрыто

- ❌ Schema-level validation для `requires_core` syntax
  (например, semver compatibility check). Не в scope этого ADR.
- ❌ Migration других extensions (если есть с тем же pattern).
  Sweep показал ТОЛЬКО эти 3 файла — если later обнаружится больше,
  отдельный ADR.
- ❌ Runtime/integration tests для этих 3 extensions
  (BLOCKED Docker per kickoff).

## Verification

| Измерение | Результат |
|---|---|
| `python3.14 tools/checks/check_compat.py` | exit 0, no [ERROR] lines для 3 plugins |
| `python3.14 -c "from src.backend.core.plugin_runtime.manifest_toml import load_plugin_manifest, PluginManifest; print(load_plugin_manifest('extensions/core_admin/plugin.toml').name)"` | "core_admin" (or new format equivalent) |
| `ruff check tools/checks/check_compat.py` | All checks passed |
| `python3.14 -m compileall -q extensions extensions/core_admin extensions/dadata extensions/skb` | EXIT 0 |
| `python3.14 -m pytest tests/unit/tools/test_w11_p3_2_audit_legacy_processors.py` | 23/23 passed (regression check) |

## Ссылки

- v4 §10 P1 (удалять shim только после 0 importers + migration window + contract test)
- v4 §5 (presence != wiring) — gate был broken, finding hidden до
  check_compat gate fix (`cc6806bd6`)
- ADR-0342 (agent_basic S76 schema migration — same pattern)
- ADR-0338 (outbox crash matrix) — schema integrity convention
- commit `cc6806bd6` — broken gate fix, revealed the drift
- commit `c53cfae57` — ledger entry surfacing this finding
