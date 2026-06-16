"""Cron Builder UI — Sprint 12 K3 W2 (thin shim, S144 W3 TD-013 regrouping).

Visual builder для cron-выражений + live preview ``Next 5 executions``
+ timezone-aware (Europe/Moscow по умолчанию) + dry-run simulation +
Save в APScheduler через admin_cron REST endpoint.

Два режима:
    * **Visual** — minute/hour/day/month/weekday dropdowns;
    * **Expression** — raw text input + validator.

Сохранение задачи отправляется POST /admin/cron/schedule.

**S144 W3 refactor**: extracted body to
:mod:`src.frontend.streamlit_app.pages._groups.cron.builder.render`.
This file is now a thin shim (Streamlit-discoverable entry-point).
"""

from __future__ import annotations

from src.frontend.streamlit_app.pages._groups.cron.builder import render

render()
