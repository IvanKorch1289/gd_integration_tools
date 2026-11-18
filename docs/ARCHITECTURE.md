# Architecture

> Актуальность: 2026-11-18. Каноничная карта архитектуры — `ARCHITECTURE.md`
> (корень репозитория) и `docs/architecture/canonical-module-map.md`;
> матрица слоёв — `tools/check_layers_contract.txt`, гейт — `tools/check_layers.py`.

## Layers

| Layer | Path | Imports Allowed |
|---|---|---|
| EntryPoints | `entrypoints/` | services, schemas, core (Protocols) |
| Services | `services/` | core, schemas |
| DSL | `dsl/` | core (контракты) + infrastructure через registries |
| Core | `core/` | только stdlib + Protocols (код из `src/` не импортируется) |
| Infrastructure | `infrastructure/` | реализует контракты из `core/` (Protocols) |
| Extensions | `extensions/<name>/` | `src.backend.core.*` + `testkit.*` + capability-checked фасады |

## Facades (Rule 1)

| Capability | Facade | DSL Method |
|---|---|---|
| Auth | `core.auth.facade.AuthFacade` | N/A — auth через ASGI-middleware (`APIKeyMiddleware`, `AuthRequiredMiddleware`) и capability-гейт движка (ADR-0456), не через builder |
| Audit | `core.audit.facade` (пакет) | N/A — шаг `audit.action` с capability `audit.write` (ADR-0454/0456) |
| Storage | `services.storage.facade.StorageFacade` | `route.from_s3()`, `route.from_file()` |
| Cache | `core.cache.facade.UnifiedCacheFacade` | `route.cache()` (read), `route.cache_write()` |
| Secrets | `infrastructure.secrets.broker.SecretBroker` (+ `core.secrets_sources.VaultSettingsSource`) | N/A — выдача только через capability-checked фасады |
| External HTTP | `core.resilience.breaker` (purgatory) | `route.proxy()` |

## Stability (Rule 6)

All external clients have: pool + Circuit Breaker (purgatory) + retry (tenacity) + healthcheck.

Состав middleware-стека — в `README.md` (раздел «Middleware»), пул/breaker/retry —
в `src/backend/core/api/__init__.py` (единая точка импорта фасадов, D160).

## ADRs

400 Architecture Decision Records в `docs/adr/` (индекс — `docs/adr/INDEX.md`,
пересборка — `make adr-index`).