# Architecture

## Layers

| Layer | Path | Imports Allowed |
|---|---|---|
| EntryPoints | `entrypoints/` | services, core/interfaces |
| Services | `services/` | infrastructure via DI/facade, core |
| DSL | `dsl/` | core/interfaces |
| Core | `core/` | interfaces only |
| Infrastructure | `infrastructure/` | external libs only |

## Facades (Rule 1)

| Capability | Facade | DSL Method |
|---|---|---|
| Auth | `core.auth.facade.AuthFacade` | `route.use_auth()` |
| Audit | `core.audit.facade` | N/A |
| Storage | `core.storage.facade.StorageFacade` | `route.from_s3()`, `route.from_file()` |
| Cache | `core.cache.facade.UnifiedCacheFacade` | `route.to_cache()` |
| Secrets | `core.audit.facade.secrets` | `route.use_secret()` |
| External HTTP | `core.resilience.breaker` (purgatory) | `route.proxy()` |

## Stability (Rule 6)

All external clients have: pool + Circuit Breaker (purgatory) + retry (tenacity) + healthcheck.

See [Stability Matrix](../README.md#stability-matrix).

## ADRs

190+ Architecture Decision Records in `docs/adr/`.