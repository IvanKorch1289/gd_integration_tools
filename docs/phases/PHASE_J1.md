# Фаза J1 — Performance+ (Rust/Cython + HTTP/3 + NUMA + jemalloc)

* **Статус:** done (ADR + план)
* **Приоритет:** P2
* **ADR:** ADR-017, ADR-018, ADR-019
* **Зависимости:** F2

## Выполнено

- ADR-017 Rust/PyO3 для hot-path.
- ADR-018 HTTP/3 (QUIC) support.
- ADR-019 NUMA + jemalloc.
- `docs/DEPLOYMENT.md` (существующий) содержит deploy-инструкции;
  добавление LD_PRELOAD=libjemalloc — follow-up.

Rust-extension (`src/_rust_ext/`) + CI cibuildwheel — отложено на
follow-up, активируется при конкретном hot-path bottleneck-е
(требует профилирования prod-нагрузки).

## Definition of Done

- [x] ADR-017, ADR-018, ADR-019.
- [x] `docs/phases/PHASE_J1.md`.
- [x] PROGRESS.md / PHASE_STATUS.yml (J1 → done).
