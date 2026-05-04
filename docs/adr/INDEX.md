# Architecture Decision Records (ADR) — индекс

Всего ADR: **51**.

| № | Заголовок | Статус | Файл |
|---|-----------|--------|------|
| 001 | ADR-001: DSL `RouteBuilder` как центральная абстракция | — | [ADR-001-dsl-central-abstraction.md](ADR-001-dsl-central-abstraction.md) |
| 001 | ADR-001: Слоистая архитектура приложения | — | [ADR-001-layered-architecture.md](ADR-001-layered-architecture.md) |
| 002 | ADR-002: Единственный DI-контейнер — svcs | — | [ADR-002-single-di-svcs.md](ADR-002-single-di-svcs.md) |
| 002 | ADR-002: svcs как единый DI-контейнер | — | [ADR-002-svcs-di-container.md](ADR-002-svcs-di-container.md) |
| 003 | ADR-003: CORS policy с явным whitelist и запретом `*` в prod | — | [ADR-003-cors-policy.md](ADR-003-cors-policy.md) |
| 003 | ADR-003: Repository Pattern через RepositoryBuilder | — | [ADR-003-repository-pattern.md](ADR-003-repository-pattern.md) |
| 004 | ADR-004: Один уровень кэша на сущность | — | [ADR-004-cache-single-layer.md](ADR-004-cache-single-layer.md) |
| 004 | ADR-004: gRPC TLS + AuthInterceptor + MQTT TLS + IMAP STARTTLS | — | [ADR-004-grpc-tls-auth.md](ADR-004-grpc-tls-auth.md) |
| 005 | ADR-005: DSL как единственный путь к бизнес-логике | — | [ADR-005-dsl-engine.md](ADR-005-dsl-engine.md) |
| 005 | ADR-005: tenacity — единственный механизм retry | — | [ADR-005-tenacity-only-retry.md](ADR-005-tenacity-only-retry.md) |
| 006 | ADR-006: EventBus через FastStream с Reply-Channel | — | [ADR-006-event-bus-faststream.md](ADR-006-event-bus-faststream.md) |
| 006 | ADR-006: Granian как prod ASGI-сервер | — | [ADR-006-granian-prod-asgi.md](ADR-006-granian-prod-asgi.md) |
| 007 | ADR-007: Аудит HTTP-запросов в ClickHouse | — | [ADR-007-audit-clickhouse.md](ADR-007-audit-clickhouse.md) |
| 007 | ADR-007: Python 3.14 Free-Threading readiness | — | [ADR-007-python-3.14-ft-readiness.md](ADR-007-python-3.14-ft-readiness.md) |
| 008 | ADR-008: NotificationGateway — единый шлюз уведомлений | — | [ADR-008-notification-gateway.md](ADR-008-notification-gateway.md) |
| 008 | ADR-008: pandas → polars полная миграция | — | [ADR-008-pandas-to-polars.md](ADR-008-pandas-to-polars.md) |
| 009 | ADR-009: httpx с HTTP/2 заменяет aiohttp | — | [ADR-009-httpx-replaces-aiohttp.md](ADR-009-httpx-replaces-aiohttp.md) |
| 009 | ADR-009: Self-Healing и автоматическое восстановление | — | [ADR-009-self-healing.md](ADR-009-self-healing.md) |
| 010 | ADR-010: CloudEvents 1.0 + Schema Registry как стандарт событий | — | [ADR-010-cloudevents-schema-registry.md](ADR-010-cloudevents-schema-registry.md) |
| 010 | ADR-010: Границы сервисов — Route→Action→Service→Repository | — | [ADR-010-service-boundary.md](ADR-010-service-boundary.md) |
| 011 | ADR-011: Open-Closed принцип — ядро закрыто, расширение через plugins/ | — | [ADR-011-open-closed-plugins.md](ADR-011-open-closed-plugins.md) |
| 011 | ADR-011: Transactional Outbox + Inbox для exactly-once | — | [ADR-011-outbox-inbox.md](ADR-011-outbox-inbox.md) |
| 012 | ADR-012: OPA + Casbin — двухуровневая авторизация | — | [ADR-012-opa-casbin-authorization.md](ADR-012-opa-casbin-authorization.md) |
| 013 | ADR-013: FastStream как унифицированная абстракция Kafka/RabbitMQ | — | [ADR-013-faststream-unification.md](ADR-013-faststream-unification.md) |
| 014 | ADR-014 — Proxy pass-through как два DSL-процессора | — | [ADR-014-proxy-pass-through.md](ADR-014-proxy-pass-through.md) |
| 014 | ADR-014: Qdrant + fastembed как production RAG stack | — | [ADR-014-qdrant-fastembed-rag-stack.md](ADR-014-qdrant-fastembed-rag-stack.md) |
| 015 | ADR-015: API Management stack (quotas + versioning + developer portal) | — | [ADR-015-api-management-stack.md](ADR-015-api-management-stack.md) |
| 016 | ADR-016: Data Lake (Iceberg/Delta) + CDC multi-source | — | [ADR-016-data-lake-stack.md](ADR-016-data-lake-stack.md) |
| 017 | ADR-017: Rust / PyO3 для hot-path в production | — | [ADR-017-rust-pyo3-hotpath.md](ADR-017-rust-pyo3-hotpath.md) |
| 018 | ADR-018: HTTP/3 (QUIC) support | — | [ADR-018-http3-quic.md](ADR-018-http3-quic.md) |
| 019 | ADR-019: NUMA affinity + jemalloc для memory-intensive workloads | — | [ADR-019-numa-jemalloc.md](ADR-019-numa-jemalloc.md) |
| 020 | ADR-020: DSL+ tooling — LSP + formatter + type-check | — | [ADR-020-dsl-plus-tooling.md](ADR-020-dsl-plus-tooling.md) |
| 021 | ADR-021: DSL interop — import/export из Camel/Spring Integration | — | [ADR-021-dsl-interop.md](ADR-021-dsl-interop.md) |
| 022 | ADR-022 — Connector SPI + ConnectorRegistry | — | [ADR-022-connector-spi.md](ADR-022-connector-spi.md) |
| 023 | ADR-023 — NotificationGateway: единый transport-gate для уведомлений | — | [ADR-023-notification-gateway.md](ADR-023-notification-gateway.md) |
| 028 | ADR-028: Security hardening — envelope encryption, immutable audit, tenant-scoped Casbin | — | [ADR-028-security-hardening.md](ADR-028-security-hardening.md) |
| 031 | ADR-031 — Durable Workflows через DSL (замена Prefect) | — | [ADR-031-dsl-durable-workflows.md](ADR-031-dsl-durable-workflows.md) |
| 032 | ADR-032 — Observability Automation (OTEL middleware, body cache, Grafana, Prometheus alerts) | — | [ADR-032-observability-automation.md](ADR-032-observability-automation.md) |
| 033 | ADR-033: ImportGateway (W24) | — | [ADR-033-import-gateway.md](ADR-033-import-gateway.md) |
| 034 | ADR-034: DSL apiVersion + migration framework | — | [ADR-034-dsl-versioning.md](ADR-034-dsl-versioning.md) |
| 035 | ADR-035: Choice JMESPath-форма как первичный способ описания condition | — | [ADR-035-choice-jmespath.md](ADR-035-choice-jmespath.md) |
| 036 | ADR-036: ResilienceCoordinator + Per-Service Fallback Chains | — | [ADR-036-resilience-coordinator.md](ADR-036-resilience-coordinator.md) |
| 037 | ADR-037: PostgreSQL → SQLite Snapshot Job для resilience-fallback | — | [ADR-037-pg-sqlite-snapshot.md](ADR-037-pg-sqlite-snapshot.md) |
| 038 | ADR-038: ActionDispatcher Gateway — единая точка диспетчеризации action | — | [ADR-038-action-dispatcher.md](ADR-038-action-dispatcher.md) |
| 039 | ADR-039: EmailReplyChannel vs NotificationGateway | — | [ADR-039-email-reply-vs-notification-gateway.md](ADR-039-email-reply-vs-notification-gateway.md) |
| 040 | ADR-040 — SecretsBackend через svcs (Wave A) | — | [ADR-040-secrets-di.md](ADR-040-secrets-di.md) |
| 041 | ADR-041: Унификация FS-watcher на `watchfiles` | — | [ADR-041-fs-watcher-unification.md](ADR-041-fs-watcher-unification.md) |
| 042 | ADR-042: `plugin.toml` — манифест плагина V11 (R1.2) | — | [ADR-042-plugin-toml-schema.md](ADR-042-plugin-toml-schema.md) |
| 043 | ADR-043: `route.toml` — манифест маршрута V11 (R1.2a) | — | [ADR-043-route-toml-schema.md](ADR-043-route-toml-schema.md) |
| 044 | ADR-044: Capability vocabulary V11 (R1.1) | — | [ADR-044-capability-vocabulary.md](ADR-044-capability-vocabulary.md) |
| 045 | ADR-045: Temporal как default workflow-backend (Wave C) | — | [ADR-045-temporal-migration-spec.md](ADR-045-temporal-migration-spec.md) |

_Сгенерировано `tools/build_adr_index.py`. Не редактировать вручную — запустите скрипт повторно._
