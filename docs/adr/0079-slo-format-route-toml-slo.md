# ADR-0079 — SLO Format: Inline `route.toml::slo` (not separate sloth YAML)

**Status:** Accepted
**Date:** 2026-05-27
**Authors:** К2, К3
**Sources:** S19 K2/K3 W1 (backbone), PLAN.md V22.4 §S19 adr-w1
**Supersedes:** N/A (new ADR; resolves R1.5 open item)

---

## Context

R1.5 (open item from pre-V22 planning) posed the question: should SLO declarations be stored in a **separate Sloth-compatible YAML file** (`slo.yml`) or **inline in `route.toml`**?

Sloth (sloth.dev) is a standard tool for generating Prometheus SLO alerts from YAML definitions. An alternative is to embed SLO directly in the route manifest as TOML fields.

The DoD for S19 required a formal decision to finalize this before production sign-off.

---

## Decision

**Embed SLO inline in `route.toml` using the `[route.slo]` TOML section (or flat `slo = {}` for single-route manifests).**

Two equivalent forms are supported by `RouteLoader`:

```toml
# Form A: flat (for single-route manifests)
slo = { p95_ms = 500, timeout_ms = 5000 }

# Form B: section (for composed routes with full metadata)
[route.slo]
p95_ms = 30
p99_ms = 100
rps_target = 200
```

Fields:
- `p95_ms` — SLO target: p95 latency in milliseconds
- `p99_ms` — SLO target: p99 latency in milliseconds (optional)
- `timeout_ms` — hard timeout for the route handler
- `rps_target` — target requests per second (for capacity planning)

---

## Alternatives Rejected

| Format | Example | Rejection Reason |
|--------|---------|-----------------|
| Separate Sloth YAML (`slo.yml`) | `sloth: { slo: 99.9, latency: p95 }` | Adds a second file to manage per route; harder to keep in sync with route.toml; breaks "single source of truth" for route manifest |
| JSON schema separate file | `slo_schema.json` + reference in route.toml | Over-engineering for the current scale (20 routes); JSON Schema is not human-friendly for SLO editing |
| No SLO (just comments) | `# SLO: p95 < 500ms` | No machine-readable SLO for Prometheus alerting, dashboards, or capacity planning |

---

## Consequences

### Positive

- Single source of truth: the route manifest (`route.toml`) contains all route metadata including SLO
- Easy to load: `RouteLoader` parses SLO in one pass; no separate file lookup
- Compatible with Prometheus alerting: `tools/slo_exporter.py` reads `route.toml` files and generates Prometheus recording rules or alerts
- Human-readable: TOML `p95_ms` and `p99_ms` are self-documenting

### Negative

- Not directly Sloth-compatible out of the box — requires a `tools/slo_to_sloth.py` converter if Sloth YAML is needed for Prometheus alert generation
- `timeout_ms` conflates SLO (business metric) with implementation timeout (operational) — mitigated by using `rps_target` for business SLO and `timeout_ms` as a circuit-breaker threshold

---

## Verification

```bash
# Verify all route.toml files have valid slo sections
python -c "
import tomllib
from pathlib import Path
for p in Path('routes').rglob('route.toml'):
    data = tomllib.loads(p.read_text())
    slo = data.get('slo') or data.get('route', {}).get('slo', {})
    assert 'p95_ms' in slo, f'{p}: missing p95_ms in slo'
    assert slo['p95_ms'] > 0, f'{p}: p95_ms must be positive'
print('All route.toml SLO sections valid')
"
```

---

## Relation to Other ADRs

- **ADR-NEW-1** (AuthorizationGateway): SLO breaches can trigger audit events via `AuthorizationGateway` — the SLO fields provide the baseline thresholds
- **S19 K4 W6** (Adaptive RAG Strategy): SLO latency targets (`p95_ms`) are used by `RAGStrategySelector` to choose retrieval strategy (dense vs hybrid vs BM25)
