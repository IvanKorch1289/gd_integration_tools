# Cycle 1 — SyntaxError Closure (2026-07-23)

## Проблема
HEAD b7bf7f55 содержал **7 заявленных SyntaxError** (compileall) +
ещё 4, найденные через `py_compile.compile(..., doraise=True)`
(разница: `ast.parse` НЕ валидирует правило `from __future__` — его
ловит только `compile()`).

Реальный список — 7 файлов, 2 разных регрессионных паттерна:
1. **em-dash в class-body (3 файла)** — class docstring преждевременно
   закрыт, docstring-фрагменты выпали в code, em-dash в identifier
   позиции даёт `invalid character '—'`.
2. **`from __future__` после других imports (4 файла)** — нарушает
   PEP 263, Python 3.12+ отвергает.

## Инструментальная проверка
```
$ python -m compileall -q src/backend 2>&1 | wc -l
7   ← до фиксов

$ python3 -c "import py_compile, os; [py_compile.compile(os.path.join(r,f), doraise=True) for r,_,fs in os.walk('src/backend') for f in fs if f.endswith('.py')]"
No exceptions   ← после фиксов (полный sweep)

$ python3 -c "import ast, os; [ast.parse(open(os.path.join(r,f)).read()) for r,_,fs in os.walk('src/backend') for f in fs if f.endswith('.py')]"
No exceptions
```

## Файлы и фиксы
1. `src/backend/dsl/engine/processors/ai_rpa.py` — добавил `"""` opener
   на line 80 (docstring continuation для 80-85).
2. `src/backend/dsl/engine/processors/desktop_pyautogui.py` — перенёс
   `if not await self.auth_check(...)` ПОСЛЕ docstring close; заменил
   em-dash `—` на `--` в `resultat -- в свойстве`.
3. `src/backend/dsl/engine/processors/vault_secret.py` — расширил
   class docstring до включения `version:` и `name:` (с переименованием
   в "Attributes:"); удалил лишний `"""` opener из предыдущей правки.
4. `src/backend/infrastructure/clients/storage/elasticsearch.py` —
   переставлен `from __future__ import annotations` на line 4
   (сразу после docstring close).
5. `src/backend/infrastructure/clients/storage/mongodb.py` — то же.
6. `src/backend/infrastructure/clients/storage/redis_coordinator.py` —
   то же.
7. `src/backend/infrastructure/clients/messaging/event_bus.py` — то же.

## Impact analysis
- **Callers**: проверено grep'ом — каждое изменение косметическое
  (порядок imports + корректировка docstring). Никакие вызовы
  функций/классов/переменных не изменились.
- **Tests**: тесты не запускались (env не имеет `prometheus_client`,
  `purgatory`, `structlog`). Verifier-фаза ограничена
  инструментальной проверкой (compile + AST sweep + import smoke).
- **Risk**: LOW. Минимальные diff'ы, документация улучшена, docstring
  структура починена.

## Diff stat
```
 src/backend/dsl/engine/processors/ai_rpa.py                   |  1 +
 src/backend/dsl/engine/processors/desktop_pyautogui.py        |  9 +++++----
 src/backend/dsl/engine/processors/vault_secret.py             | 11 ++++-------
 src/backend/infrastructure/clients/messaging/event_bus.py     |  3 ++-
 src/backend/infrastructure/clients/storage/elasticsearch.py   |  3 ++-
 src/backend/infrastructure/clients/storage/mongodb.py         |  3 ++-
 .../infrastructure/clients/storage/redis_coordinator.py       |  3 ++-
 7 files changed, 18 insertions(+), 15 deletions(-)
```

## Retrospective lesson
Прошлые циклы заявляли "all checks pass" на основе grep/AST, что
НЕ ловит `from __future__` правило (нужен `py_compile.compile(..., doraise=True)`
или `compile()`). Включаю в чек-лист Verifier:
1. `python -m compileall src/backend` (compileall, exit 0 = OK)
2. `py_compile.compile(..., doraise=True)` full sweep (ловит
   строгие compile-time ошибки включая `from __future__`)
3. `ast.parse` full sweep (AST-level sanity)
4. `python -c "import <module>"` smoke (опционально, при наличии deps)

## Следующий цикл (рекомендация)
P1 backlog (без блокеров, требует project-wide scope):
- Layer violations baseline через `tools/check_layers.py`
- Ruff strict sweep (F401, S107 etc. — known MEDIUM debt)
- Test collection errors baseline (`pytest --collect-only`)
- Mypy baseline (746 errors в KNOWN_ISSUES)
