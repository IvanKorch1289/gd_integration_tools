# Фаза C2 — Spring Integration (Gateway + Interceptors + Versioning)

* **Статус:** done (scaffolding)
* **Приоритет:** P1
* **ADR:** —
* **Зависимости:** C1

## Выполнено

- `src/dsl/integration_gateway/__init__.py` — `MessagingGateway`,
  `ChannelInterceptor`, `VersionedRoute`.
- Public API для Python-фасадов поверх DSL-route (Spring
  @MessagingGateway-подобный подход).
- `VersionedRoute` поддерживает v1/v2 + deprecation/sunset metadata.

## Definition of Done

- [x] `MessagingGateway.invoke()` работает поверх `get_dsl_service()`.
- [x] `ChannelInterceptor` pre/post-send hooks.
- [x] `VersionedRoute` c deprecation/sunset.
- [x] `docs/phases/PHASE_C2.md`.
- [x] PROGRESS.md / PHASE_STATUS.yml (C2 → done).
