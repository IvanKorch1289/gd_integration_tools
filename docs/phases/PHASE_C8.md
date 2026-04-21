# Фаза C8 — Transformations (единый фасад 7 engines)

* **Статус:** done (scaffolding + 4 engine)
* **Приоритет:** P1
* **ADR:** —
* **Зависимости:** C7

## Выполнено

`src/dsl/transform/__init__.py` — единый фасад
`transform(expr, data, engine='jmespath'|'jq'|'jinja2'|'xpath'|'xslt'|'bloblang'|'dataweave')`.

Рабочие engines (scaffold-уровень):
- **jmespath** — работает по умолчанию.
- **jq** (через pyjq) — при наличии пакета.
- **jinja2** — работает.
- **xpath/xslt** (lxml) — работает.

Engines, требующие external bridge / lite-импорт в follow-up:
- **bloblang** — через benthos CLI (future).
- **dataweave-lite** — на pyparsing (future).

## Definition of Done

- [x] Фасад `transform()`.
- [x] 4 engine работают.
- [x] 2 engine помечены RuntimeError до реализации.
- [x] `docs/phases/PHASE_C8.md`.
- [x] PROGRESS.md / PHASE_STATUS.yml (C8 → done).
