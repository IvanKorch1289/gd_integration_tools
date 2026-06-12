# GD Integration Tools — Cookbooks

Практические рецепты (how-to guides) для production deployments.
Каждый cookbook — self-contained tutorial: goal, prerequisites,
step-by-step instructions, verification, troubleshooting.

**Audience**: developers, DevOps, architects, AI engineers.
**Style**: pragmatic, code-first, no excessive explanation.

## Available cookbooks

| # | Cookbook | Sprint | Status |
|---|----------|--------|--------|
| 1 | [AI agent с tools whitelist + CapabilityGate](01-ai-agent-tools-whitelist.md) | S76+S79 | ✅ ready |
| 2 | [Multi-instance outbox claim (atomicity + lease)](02-outbox-multi-instance-claim.md) | S72 | ✅ ready |
| 3 | [Notebook execution с E2B sandbox](03-notebook-e2b-sandbox.md) | S75 | ✅ ready |
| 4 | [CircuitBreaker deployment (per-route resilience)](04-circuit-breaker-deployment.md) | S81 | ✅ ready |
| 5 | [LiteLLM Gateway в PoolHealthMonitor](05-litellm-pool-health-monitoring.md) | S80 | ✅ ready |

## Cookbook structure (template)

Each cookbook follows this structure:

1. **Goal** — what you'll achieve
2. **Prerequisites** — required setup, dependencies
3. **Step-by-step** — concrete code/YAML/commands
4. **Verification** — how to confirm it works
5. **Troubleshooting** — common issues + fixes
6. **Related** — links to ADRs, docs, related cookbooks

## When to write a new cookbook

* User asks "how do I use X" — X needs hands-on tutorial
* Major feature released (Sprint) — write cookbook for primary use case
* Common pattern in support — extract into cookbook
