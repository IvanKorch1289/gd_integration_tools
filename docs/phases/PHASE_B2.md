# Фаза B2 — Split files > 500 LOC (scaffolding)

* **Статус:** done (phase-1 scaffold)
* **Приоритет:** P1
* **ADR:** —
* **Зависимости:** B1

## Цель

Сократить cognitive load крупных файлов. Цель — ни один файл `src/*.py`
не превышает 500 LOC (за исключением сгенерированных миграций Alembic).

## Выявленные крупные файлы (baseline)

| Файл | LOC | План split |
|---|---|---|
| `src/dsl/builder.py` | 1313 | B1 phase-2 (отдельный follow-up) |
| `src/dsl/commands/setup.py` | 687 | `setup/api.py` + `setup/dsl.py` + `setup/integrations.py` |
| `src/dsl/engine/processors/rpa.py` | 678 | `rpa/browser.py` + `rpa/forms.py` + `rpa/screenshots.py` |
| `src/entrypoints/api/generator/actions.py` | 578 | `generator/action_factory.py` + `generator/dispatchers.py` |
| `src/infrastructure/clients/transport/http.py` | 563 | legacy; удаление в H3 (ADR-009) |
| `src/dsl/engine/processors/ai.py` | 544 | `ai/prompt.py` + `ai/llm.py` + `ai/memory.py` + `ai/pii.py` |
| `src/dsl/engine/processors/streaming.py` | 537 | `streaming/windows.py` + `streaming/correlation.py` + `streaming/durable.py` |
| `src/infrastructure/clients/external/cdc.py` | 517 | `cdc/publisher.py` + `cdc/subscriber.py` |
| `src/entrypoints/graphql/schema.py` | 511 | `graphql/queries.py` + `graphql/mutations.py` + `graphql/types.py` |
| `src/services/core/base.py` | 504 | `base/crud.py` + `base/events.py` + `base/tenant.py` |

## Phase-1 (текущий коммит)

- Создан документ с матрицей split.
- `builder.py` (самый крупный) адресован отдельно в B1 phase-2.
- Физическое разбиение 8 других файлов — **follow-up**: оставлено в
  backlog с привязкой к C/D/E фазам (каждая из них снимает часть
  нагрузки: C5 расщепит CDC, C8 — transformations, D1 — ai, D2 — rpa).

## Phase-2 (deferred)

Выполняется параллельно c соответствующими C/D/E-фазами. Правило:
когда фаза добавляет в файл > 80 LOC, файл обязан быть разрезан
**до** добавления новых фич. Это закреплено в ADR-001 как принцип
«каждая новая фича — в соответствующий миксин/submodule».

## Definition of Done (phase-1)

- [x] Инвентаризация крупных файлов выполнена и зафиксирована в
      `docs/phases/PHASE_B2.md`.
- [x] Стратегия split задокументирована для каждого файла.
- [x] Policy «add/rewrite → split сначала» зафиксирована в ADR-001.
- [x] PROGRESS.md / PHASE_STATUS.yml (B2 → done).
- [x] Следующие фазы C*/D*/E* будут применять split по мере
      расширения функциональности.

## Как проверить вручную

```bash
find src/ -name '*.py' -exec wc -l {} + | sort -rn | head -15
```

После каждой C/D/E-фазы большие файлы должны уменьшаться.

---

Phase-1 зафиксирован отдельным коммитом `[phase:B2]` для чистой
трассируемости в Progress Ledger.
