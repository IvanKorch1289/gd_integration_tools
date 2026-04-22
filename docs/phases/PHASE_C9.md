# Фаза C9 — Codecs (единый фасад + банковские opt-in)

* **Статус:** done (scaffolding)
* **Приоритет:** P1
* **ADR:** —
* **Зависимости:** C8

## Выполнено

`src/dsl/codec/__init__.py`:
- `decode_as(fmt, raw)` / `encode_as(fmt, data)`.
- Работают: json, yaml, xml, msgpack, cbor.
- Банковские (opt-in `gdi[banking]`): mt, hl7, iso8583 — через отдельные
  пакеты (swiftmt, hl7apy, iso8583), ошибка с подсказкой установки.

pyproject: `msgpack`, `cbor2`, `xmltodict` — добавлены (C9-ADD).

## Definition of Done

- [x] Фасад decode_as/encode_as.
- [x] 5 стабильных форматов работают.
- [x] Банковские форматы opt-in с понятным RuntimeError.
- [x] `docs/phases/PHASE_C9.md`.
- [x] PROGRESS.md / PHASE_STATUS.yml (C9 → done).
