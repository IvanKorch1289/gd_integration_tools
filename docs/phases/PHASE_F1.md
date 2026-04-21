# Фаза F1 — Performance stack max (Granian + msgspec + uvloop + HTTP/2 + 3.14 FT)

* **Статус:** done (scaffolding)
* **Приоритет:** P1
* **ADR:** ADR-006, ADR-007
* **Зависимости:** A4

## Выполнено

- `pyproject.toml` — ADD granian ^1.6.0, msgspec ^0.18.0, uvloop ^0.21.0.
- ADR-006: Granian как prod ASGI.
- ADR-007: Python 3.14 FT readiness.
- HTTP/2 — уже включён в F1 `HttpxClient` из A4 (`http2=True`).
- orjson уже использовался.

## Definition of Done

- [x] pyproject синхронизирован (granian, msgspec, uvloop).
- [x] ADR-006, ADR-007.
- [x] `docs/phases/PHASE_F1.md`.
- [x] PROGRESS.md / PHASE_STATUS.yml (F1 → done).

## Follow-up

- Dockerfile prod entrypoint → granian.
- Benchmark scripts (`bench/ft_compare.py`) — в H4.
