# ADR-0101: Lazy-import pattern для streamlit-dependent helpers (testability boundary)

**Date:** 2026-06-09
**Status:** Accepted (S77 W4)
**Sprint:** S77
**Deciders:** core team
**Supersedes:** —
**Related:** S77 W3 (`c1461298 refactor(streamlit): S77 W3 — split 31_DSL_Visual_Editor.py 1269→1082 LOC`), S77 W3 followup (`0ffc4141 fix(streamlit): S77 W3 followup — P0 init order + P1 docstring fixes`), S62 lesson (streamlit/missing-extra fix из S63 W1), S77 W2 (ADR-0100)

## Context

Streamlit — это **optional dependency** (только в `[frontend]` extra venv). S63 W1 уже зафиксировал: `streamlit` не должен быть в `runtime-required` deps. Но ряд helper-функций (undo/redo history, YAML sync, drag-drop) **используют `st.session_state` / `st.sidebar` / `st.tabs`** и должны жить в shared modules для unit-тестирования.

**Проблема:** module-level `import streamlit as st` в shared module
1. ломает импорт модуля в test-runner без `[frontend]` extra (ImportError);
2. делает невозможным unit-тестирование pure-функций, которые случайно ссылаются на `st`;
3. заставляет дублировать helpers inline в main page file (god-file pattern).

S77 W3 извлёк 478 LOC pure-логики из 31_DSL_Visual_Editor.py (1269 → 1082 LOC) в `pages/_editor/` package: `constants.py`, `history.py`, `yaml_sync.py`, `__init__.py`. Из них `history.py` и `yaml_sync.py` зависят от `streamlit.session_state` (undo-стек, sync yaml to UI).

## Decision

**В shared module, который может быть импортирован из unit-тестов:**

1. **НЕ делать** module-level `import streamlit` или `import streamlit as st`.
2. **Lazy-import** через helper `_require_streamlit() -> object` внутри функций:
   ```python
   def _require_streamlit():
       """Lazy import streamlit (module-level импорт ломает тесты без [frontend]).

       Returns runtime-imported ``streamlit`` module. Annotation
       intentionally untyped: TYPE_CHECKING импорт был бы flag'нут F401,
       а string-quoted ``"st"`` requires explicit forward-ref management.
       Plain ``-> object`` is honest: callers treat result as namespace.
       """
       import streamlit as st
       return st
   ```
3. **Type annotation helper'a = untyped (no `-> "streamlit.ModuleType"`)**. Callers
   treat result as namespace (duck-typed `.session_state`, `.sidebar`, `.tabs`).
   Type ignore `[type-arg]` НЕ использовать — это культивирует скрытые баги.
4. **Pure-функции** (без `st` зависимостей) — держать в отдельных модулях (`constants.py`),
   тестировать без `streamlit` вообще.
5. **Streamlit rendering** (sidebar palette, drag-drop canvas, tabs) — оставлять inline
   в main page file, не извлекать: тесно связан с `st.session_state` / `st.sidebar` / `st.tabs`,
   extraction cost > benefit.

## Rationale

### Почему lazy-import, а не TYPE_CHECKING

```python
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    import streamlit as st  # F401 violation, требует noqa
```

TYPE_CHECKING guard:
- flag'нется ruff F401 (unused import);
- требует `# noqa: F401` на каждом импорте — noise;
- фактический runtime-import всё равно нужен внутри функций (session_state не optional).

### Почему untyped return, а не `-> "streamlit"`

```python
from __future__ import annotations  # PEP 563

def _require_streamlit() -> "st":  # requires forward-ref management
    import streamlit as st
    return st
```

Forward ref:
- требует `from __future__ import annotations` ИЛИ explicit `streamlit.ModuleType` import;
- test-runner без streamlit не может resolve "st" forward-ref;
- создаёт illusion of type-safety, хотя callers реально duck-type.

Untyped `-> object`:
- честный signal "callers treat as namespace";
- совместим с любым runtime (with/without streamlit);
- mypy strict не ругается (object = supertype всего).

### Почему extract pure-logic, но НЕ rendering

| Layer | Зависит от streamlit? | Testability | Action |
|-------|----------------------|-------------|--------|
| Pure data (constants, defaults) | No | trivial | Extract |
| Pure functions (yaml↔steps conversion) | No | trivial | Extract |
| Session-state helpers (undo/redo) | Yes (lazy) | requires [frontend] | Extract + lazy |
| Render functions (sidebar, tabs, drag) | Yes (full) | integration only | Keep inline |

## Verification (S77 W3 measurements)

```bash
# Unit tests без [frontend] extra — passed
pytest tests/unit/frontend/test_dsl_editor_helpers.py
# 19/19 passed в 0.40s (S77 W3 mainline)
# 21/21 passed в 0.47s (S77 W3 followup, +2 try_load tests)

# mypy strict на pure modules
mypy --no-incremental --strict src/frontend/streamlit_app/pages/_editor/
# Success: no issues found in 4 source files

# ruff check
ruff check src/frontend/streamlit_app/pages/_editor/
# All checks passed
```

## Lessons reinforced

1. **Optional deps require lazy imports, не TYPE_CHECKING guards** (S63 W1 lesson extended).
2. **Untyped helper return type > fake type safety** — better honest signal than illusion of safety.
3. **Testability boundary = module boundary**: если функция может быть протестирована
   без опциональной зависимости, она должна быть в отдельном модуле.
4. **Extraction cost/benefit asymmetry**: pure logic → extract (high benefit), render → keep
   inline (low benefit, high coupling cost).

## When to apply this pattern

Apply when ALL of:
- Module lives in `src/frontend/streamlit_app/` или `src/frontend/streamlit_helpers/`.
- Functionality может быть unit-tested без streamlit runtime.
- Function использует `st.session_state`, `st.sidebar`, `st.tabs`, или другой streamlit API.

Don't apply when:
- Module явно требует streamlit (main page files, integration test fixtures).
- Function pure (no streamlit dependency) — extract без lazy-import overhead.
- Function делает rendering (sidebar palette, drag-drop canvas) — keep inline.

## References

- S77 W3 commit `c1461298 refactor(streamlit): S77 W3 — split 31_DSL_Visual_Editor.py 1269→1082 LOC`
- S77 W3 followup commit `0ffc4141 fix(streamlit): S77 W3 followup — P0 init order + P1 docstring fixes`
- ADR-0100 (S77 W2) — verify-before-refactor pattern.
- S63 W1 TD-008 — streamlit/missing-extra fix.
- S62 lesson (memory) — streamlit optional import pattern.
