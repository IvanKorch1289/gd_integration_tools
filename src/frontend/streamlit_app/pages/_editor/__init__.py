"""Helper-модули для DSL Visual Editor (S77 W3 split).

Streamlit page ``31_DSL_Visual_Editor.py`` был 1269 LOC god-file
(S77 W2 backlog от v28 ro-аудита). Чистая логика вынесена сюда:

* :mod:`.constants` — STEP_PALETTE, PROCESSOR_ICONS, VISUAL_PROCESSORS
  (метаданные процессоров), ``default_yaml()`` шаблон.
* :mod:`.history` — undo/redo (6 функций: ``init_history``,
  ``push_history``, ``can_undo``, ``can_redo``, ``undo``, ``redo``).
* :mod:`.yaml_sync` — YAML ↔ steps (4 функции: ``yaml_to_steps``,
  ``build_yaml_from_steps``, ``try_load``, ``sync_yaml``).

Rendering (Streamlit UI) остаётся в самой странице — render-функции
тесно связаны с ``st.session_state`` / ``st.sidebar`` / ``st.tabs``
и не извлекаются без значительного overhead.

API backward-compatible: каждое private имя из старого
``31_DSL_Visual_Editor.py`` re-exported здесь с тем же signature.
"""

from __future__ import annotations

from src.frontend.streamlit_app.pages._editor.constants import (
    PROCESSOR_ICONS,
    STEP_PALETTE,
    VISUAL_PROCESSORS,
    default_yaml,
)
from src.frontend.streamlit_app.pages._editor.history import (
    can_redo,
    can_undo,
    init_history,
    push_history,
    redo,
    undo,
)
from src.frontend.streamlit_app.pages._editor.yaml_sync import (
    build_yaml_from_steps,
    sync_yaml,
    try_load,
    yaml_to_steps,
)

__all__ = (
    "PROCESSOR_ICONS",
    "STEP_PALETTE",
    "VISUAL_PROCESSORS",
    "build_yaml_from_steps",
    "can_redo",
    "can_undo",
    "default_yaml",
    "init_history",
    "push_history",
    "redo",
    "sync_yaml",
    "try_load",
    "undo",
    "yaml_to_steps",
)
