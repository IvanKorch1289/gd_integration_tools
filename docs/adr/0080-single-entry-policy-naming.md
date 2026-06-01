# ADR-0080 — Single Entry Policy Naming Convention

**Status:** Accepted
**Date:** 2026-05-27
**Authors:** К2
**Sources:** S19 K2 W1 (backbone), PLAN.md V22.4 §S19 adr-w1
**Supersedes:** N/A (new ADR; resolves R1.7 open item)

---

## Context

R1.7 (open item from pre-V22 planning) asked: what naming convention should be used for the **Single Entry** policy facade classes and decorators?

V22 introduced "Single Entry" as an architectural principle: each subsystem has exactly one public facade that routes to underlying implementations. For resilience, the facade is `ResilienceCoordinator`; for retries it's `@with_retry`; for circuit-breaking it's `@with_circuit_breaker`.

The naming convention question was: should these be named with `_policy` suffix (`RetryPolicy`, `CircuitBreakerPolicy`) or with a verb-first pattern (`WithRetry`, `ApplyCircuitBreaker`) or with a `Coordinator` suffix for facades?

---

## Decision

**Naming convention for Single Entry components:**

| Component Type | Suffix/Pattern | Example |
|---------------|----------------|---------|
| Facade class (routes to impls) | `Coordinator` | `ResilienceCoordinator`, `AuthCoordinator` |
| Decorator (wraps callables) | `with_` prefix | `@with_retry`, `@with_circuit_breaker`, `@with_bulkhead` |
| Config dataclass (settings) | `Spec` suffix | `RetrySpec`, `CircuitBreakerSpec`, `BulkheadSpec` |
| Policy enum (strategy choice) | `Policy` suffix | `RetryPolicy`, `CircuitBreakerPolicy` |
| Exception | `Error` suffix | `CircuitBreakerOpenError`, `BulkheadRejectedError` |

All public Single Entry exports are re-exported from the subsystem's `__init__.py` and from the parent `core/resilience/__init__.py`.

---

## Alternatives Rejected

| Pattern | Example | Rejection Reason |
|---------|---------|-----------------|
| `_policy` suffix on facades | `RetryPolicy`, `CircuitBreakerPolicy` | Confusing: "policy" usually means a settings/config object, not a runtime coordinator |
| Verb-first decorators | `@retry`, `@circuit_breaker` | Too generic; conflicts with stdlib and third-party packages; `@retry` from `tenacity` is the most popular |
| `Handler` suffix | `RetryHandler`, `BreakerHandler` | "Handler" implies a passive wrapper; Single Entry facades actively coordinate multiple impls |
| No convention (ad-hoc) | Various | Leads to inconsistency across subsystems; onboarding cost for new developers |

---

## Consequences

### Positive

- Consistent naming across all Single Entry subsystems — new developers can infer the pattern
- Decorator prefix `with_` avoids conflicts with popular third-party packages (`@retry` vs `@with_retry`)
- Facade suffix `Coordinator` signals that the class routes to multiple implementations, not just a single function
- Config dataclass suffix `Spec` is already used in Pydantic (e.g., `BrokerSpec` in FastStream)

### Negative

- Requires migrating some existing class names if they don't follow the convention (e.g., `RPACallPolicy` → `ResilienceCoordinator` for RPA)
- The `Coordinator` suffix may be overused — if a class is not actually coordinating multiple implementations, it should not use this suffix

---

## Verification

```bash
# Verify Single Entry naming convention
python -c "
import ast, re
from pathlib import Path

violations = []
for py in Path('src/backend/core/resilience').rglob('*.py'):
    tree = ast.parse(py.read_text())
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            name = node.name
            bases = [b.attr if isinstance(b, ast.Attribute) else b.id if isinstance(b, ast.Name) else '' for b in node.bases]
            # Coordinator without Coordinator suffix
            if 'Coordinator' in name and not name.endswith('Coordinator'):
                violations.append(f'{py}: {name} contains Coordinator but wrong suffix')
            # Policy without Policy as enum/config
            if 'Policy' in name and not any(s in name for s in ['RetryPolicy', 'CircuitBreakerPolicy', 'BulkheadPolicy']):
                violations.append(f'{py}: {name} has Policy in name')
if violations:
    print('\n'.join(violations))
    exit(1)
print('Naming convention OK')
"
```

---

## Relation to Other ADRs

- **ADR-NEW-2** (Decoratively Composable Middleware Chain): Middleware Registry uses the same `Coordinator` suffix pattern for `MiddlewareChainCoordinator`
- **ADR-0052** (Policy Decorator Order): Policy decorator order is orthogonal but complementary — `@with_retry` wraps `@with_circuit_breaker` (retry outermost)
