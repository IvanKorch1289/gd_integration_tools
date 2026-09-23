"""RPA Recorder → DSL Draft (Wave 3 #16).

Проблема:
    Создание RPA-flow вручную долго:
    - Записать browser-actions в Playwright.
    - Преобразовать в DSL draft.
    - Запустить нормализацию + lint + tests.

Решение:
    ``RPARecorder`` — pure-Python DSL draft generator:

    1. ``RecordedAction`` — single browser action (click/type/navigate).
    2. ``parse_recorded_actions(actions)`` — из list → DSL draft.
    3. ``DSLStep`` — typed action (browser.open, browser.click, browser.fill).
    4. ``generate_route_draft(actions, route_id)`` → {route.yaml, test_*.py}.
    5. Export via export_route_draft helper.

Usage::

    from src.backend.core.rpa_recorder import (  # noqa: F401 — re-export
        RPARecorder, RecordedAction, generate_route_draft,
    )

    recorder = RPARecorder()
    recorder.add_action(RecordedAction("navigate", url="https://example.com"))
    recorder.add_action(RecordedAction("fill", selector="input#q", value="hello"))
    recorder.add_action(RecordedAction("click", selector="button.search"))

    draft = generate_route_draft(recorder.actions(), route_id="search-flow")
    Path("extensions/search/").mkdir(exist_ok=True)
    export_route_draft(draft, "extensions/search")
"""

from __future__ import annotations

from src.backend.core.rpa_recorder.recorder import (  # noqa: F401 — re-export
    DSLStep,
    RecordedAction,
    RecorderActionType,
    RPARecorder,
    export_dsl_draft,
    generate_route_draft,
    get_rpa_recorder,
    parse_recorded_actions,
)

__all__ = (
    "DSLStep",
    "RPARecorder",
    "RecordedAction",
    "RecorderActionType",
    "export_dsl_draft",
    "generate_route_draft",
    "get_rpa_recorder",
    "parse_recorded_actions",
)
