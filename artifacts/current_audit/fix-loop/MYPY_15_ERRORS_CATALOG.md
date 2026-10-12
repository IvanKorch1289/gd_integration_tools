# P0-03 — каталог 15 mypy-ошибок (`make type-check-budget`, budget = 5)

Дата снятия: 2026-10-12. Команда: `make type-check-budget` → exit 2,
`mypy errors: 15 (max=5, baseline=30)`.

Снято по слоям (`mypy --follow-imports=silent --cache-dir=/dev/null <layer>`):

| Слой | Ошибок |
|---|---:|
| `src/backend/core` | 2 |
| `src/backend/services` | 9 |
| `src/backend/infrastructure` | 0 |
| `src/backend/dsl` | 2 |
| entrypoints + plugins + прочее | 2 (не разложено) |
| **Итого** | **15** |

## Ошибки (по состоянию на 2026-10-12)

### dsl — 2 (`src/backend/dsl/engine/processors/function_call.py`)

```
163: error: "self" parameter missing for a non-static method
                (or an invalid type for self)              [misc]
268: error: Invalid self argument "CallFunctionProcessor" to attribute
                function "_validate_module_whitelist"
                with type "Callable[[str, ExecutionContext], None]" [misc]
     note: Looks like the first special argument in a method is not
           named "self", "cls", or "mcs", maybe it is missing?
```

**Существенная находка помимо типизации.** Метод объявлен как

```python
def _validate_module_whitelist(module_name: str, context: ExecutionContext) -> None:
```

— без `self`, но вызывается как `self._validate_module_whitelist(...)`
(`function_call.py:268`). Это не только ошибка аннотации: в теле метода
по docstring (строки 164-169) читается `context.properties.call_function_modules`,
а `ExecutionContext` поля `properties` **не имеет** (оно есть только у
`Exchange`). Это совпадает с P0, зафиксированным в `CLAUDE.md` («DSL Dual-Mode
Principle»): ветка чтения whitelist из `context.properties` — мёртвый код,
whitelist недостижим, и при `call_function_whitelist_strict=True` (дефолт)
любой шаг `call_function` даёт `PermissionError`.

**Правильный фикс — не только сигнатура.** Нужен ADR на источник whitelist
(уже отмечено в CLAUDE.md как требующее решения). Минимально безопасный шаг:
добавить `self` в сигнатуру + regression-тест, фиксирующий текущее поведение
(`PermissionError`), и **не** расширять scope без ADR.

### core — 2 (`src/backend/core/ai/pydantic_ai_adapter.py`)

```
140: error: Cannot instantiate abstract class "_SimpleStreamedResponse"
                with abstract attributes "provider_name", "provider_url"
                and "timestamp"                        [abstract]
165: error: Incompatible return value type
                (got "Provider[Any]", expected "str")    [return-value]
```

Требует правки класса-заглушки `_SimpleStreamedResponse` (реализовать
абстрактные атрибуты или наследоваться от корректной базы `pydantic_ai`).

### services — 9

```
services/ai/agents/langgraph_postgres_saver.py:140:
  error: Module "langchain_postgres" has no attribute "AsyncPostgresSaver" [attr-defined]

services/rpa/browser_pool.py:203:
  error: Name "async_api" already defined (by an import)                  [no-redef]

services/ai/agents_pydantic/adapter.py:21:
  error: Module "pydantic_ai.result" has no attribute "StreamedResponse"  [attr-defined]
services/ai/agents_pydantic/adapter.py:27:
  error: Cannot assign to a type                                       [misc]
services/ai/agents_pydantic/adapter.py:28:
  error: Cannot assign multiple types to name "ModelMessage"
         without an explicit "type[...]" annotation                      [misc]
services/ai/agents_pydantic/adapter.py:29: error: Cannot assign to a type          [misc]
services/ai/agents_pydantic/adapter.py:30: error: Cannot assign to a type          [misc]
services/ai/agents_pydantic/adapter.py:31: error: Cannot assign to a type          [misc]
```

Паттерн `Cannot assign to a type` в `agents_pydantic/adapter.py:27-31` —
типичные conditional-reimport'ы вида `if TYPE_CHECKING: X = A else: X = B`,
которые mypy не принимает без `type[...]`. Это **одна логическая правка**
(рефакторинг shim-импортов), не семь.

Аналогично `langchain_postgres.AsyncPostgresSaver` и
`pydantic_ai.result.StreamedResponse` — расхождения версий API-библиотек;
требуют либо обновления зависимости, либо адаптера (`getattr`-fallback).
По правилу «Не добавляй новую библиотеку, если уже присутствующая покрывает
use case» — обновление версии, а не новая зависимость.

## Рекомендация по разбиению на atomic-коммиты

| # | Скоуп | Файлов | Ошибок снимает |
|---|---|---:|---:|
| M1 | `function_call.py`: `self` + regression-тест текущего поведения | 1 + 1 test | 2 |
| M2 | `pydantic_ai_adapter.py`: абстрактные атрибуты + тип возврата | 1 | 2 |
| M3 | `agents_pydantic/adapter.py`: `type[...]` в shim-реэкспортах | 1 | 6 |
| M4 | `browser_pool.py`: переименование затенённого `async_api` | 1 | 1 |
| M5 | Версионные расхождения `langchain_postgres` / `pydantic_ai` | 1-2 | 2 |
| M6 | entrypoints/plugins (остаток) | ? | 2 |

После M1-M5: `mypy errors: 0..2` → `make type-check-budget` проходит при
`--max 5`. Baseline `.baselines/mypy.json` обновлять **только после**
зелёного прогона (иначе ratchet зафиксирует регресс).

**Правило:** каждый шаг = сначала падающий regression-тест, затем фикс,
затем `make type-check-budget` для подтверждения, что число ошибок упало,
и отдельный atomic-коммит.