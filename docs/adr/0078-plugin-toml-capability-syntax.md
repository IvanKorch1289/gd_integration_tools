# ADR-0078 — plugin.toml Capability Syntax: Array Format (`[[capabilities]]`)

**Status:** Accepted
**Date:** 2026-05-27
**Authors:** К1
**Sources:** S19 K1 W1 (backbone), PLAN.md V15 §R-V15-1, V22.4 §S19 adr-w1
**Supersedes:** N/A (new ADR; resolves R1.1 open item)

---

## Context

R1.1 (open item from pre-V22 planning) raised the question: should `plugin.toml` declare capabilities as a **flat key-value map** (`capabilities.name = "value"`) or as a **TOML array of tables** (`[[capabilities]]` with `name` and `scope` fields)?

The capability-gate V11.1 (`CapabilityGate` in `core/plugin_runtime/`) requires each capability to carry a `scope` for fine-grained authorization. A flat-key format cannot express scope cleanly — it would require encoding scope into the key name (e.g., `capabilities.db.read = "files"`), which becomes unwieldy and non-extensible.

---

## Decision

**Use TOML array-of-tables format: `[[capabilities]]` with `name` and `scope` fields.**

Example from `extensions/core_entities/files/plugin.toml`:

```toml
[[capabilities]]
name = "db.read"
scope = "files"

[[capabilities]]
name = "db.write"
scope = "files"

[[capabilities]]
name = "fs.read"
scope = "s3://*"
```

Each `[[capabilities]]` entry is independently parsed by `CapabilityGate.check()` via `PluginLoader._parse_capabilities()`.

---

## Alternatives Rejected

| Format | Example | Rejection Reason |
|--------|---------|-----------------|
| Flat key-value | `capabilities.db_read = "files"` | Scope must be encoded in key name; breaks with multi-scope capabilities; non-extensible for future fields (e.g., `grant_type`) |
| Single-string array | `capabilities = ["db:files", "fs:s3://*"]` | Colon-delimited encoding is fragile; no validation schema; hard to parse in LSP |

---

## Consequences

### Positive

- Scope is a first-class field, validated by `CapabilityScopeValidator`
- Array format is self-documenting and LSP-friendly (each entry is a block)
- Extensible: new per-capability fields (e.g., `granted_at`, `expires`) can be added without breaking existing plugins
- Used consistently across all 3 existing plugins (`credit_pipeline`, `core_entities_files`, `test_plug`)

### Negative

- Requires plugin authors to write `[[capabilities]]` (slightly more verbose than a flat map)
- Backward-compatible: existing plugins must migrate (automated via `make plugin-migrate-capabilities`)

---

## Verification

```bash
# Validate all plugin.toml files use [[capabilities]] array format
python -c "
import tomllib
from pathlib import Path
for p in Path('extensions').rglob('plugin.toml'):
    data = tomllib.loads(p.read_text())
    caps = data.get('capabilities', [])
    assert isinstance(caps, list), f'{p}: capabilities must be array'
    for c in caps:
        assert 'name' in c, f'{p}: capability missing name'
        assert 'scope' in c, f'{p}: capability missing scope'
print('All plugin.toml files valid')
"
```

---

## Relation to Other ADRs

- **ADR-NEW-1** (AuthorizationGateway): `AuthorizationGateway` consumes capabilities via `CapabilityGate.check(plugin, capability, scope)` — the array format is the source of truth
- **ADR-NEW-5** (AI Safety Capability Unification): AI workspace capabilities use the same `[[capabilities]]` format with `fs.write.<scope>` naming
