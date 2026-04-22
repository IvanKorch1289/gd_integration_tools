# Фаза C10 — Connectors (IoT + Web3 + Legacy)

* **Статус:** done (scaffolding + extras-метки)
* **Приоритет:** P1
* **ADR:** —
* **Зависимости:** C9

## Выполнено

- `src/entrypoints/iot/__init__.py` — OPC-UA / Modbus / CoAP /
  LoRaWAN маркеры (`is_iot_available()`); импорты ленивые, сами
  пакеты — opt-in.
- `src/entrypoints/web3/__init__.py` — EVM JSON-RPC (web3.py).
- `src/entrypoints/legacy/__init__.py` — TN3270/5250 (py3270/pytn5250).
- `pyproject.toml` — extras `gdi[iot]`, `gdi[web3]`, `gdi[legacy]`,
  `gdi[banking]` объявлены (пакеты доустанавливаются пользователем —
  они проприетарны/тяжелы и не подходят для базовой установки).

## Definition of Done

- [x] 3 подмодуля создано.
- [x] Функции `is_*_available()` позволяют graceful-detect.
- [x] Extras объявлены.
- [x] `docs/phases/PHASE_C10.md`.
- [x] PROGRESS.md / PHASE_STATUS.yml (C10 → done).

## Follow-up

Детальные коннекторы per protocol (opcua_server.py / modbus_client.py
и т.д.) — по мере появления реальных интеграционных проектов у заказчика.
