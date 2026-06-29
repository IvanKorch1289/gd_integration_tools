"""Cron Dashboard UI — Sprint 12 K5 W3 (thin shim, S144 W4 TD-013 regrouping).

Сводный dashboard для всех scheduled workflows:

* Таблица: name, cron_expr, tz, last_run_at, next_run_at, success_rate(7d),
  status (enabled/paused).
* Action кнопки per row: Pause / Resume / Run now / Delete.
* Top-level metrics: total scheduled / today runs / today failed.
* Auto-refresh каждые 30 сек.

**S144 W4 refactor**: extracted body to
:mod:`src.frontend.streamlit_app.pages._groups.cron.dashboard.render`.
This file is now a thin shim (Streamlit-discoverable entry-point).
"""

from __future__ import annotations

import streamlit as st

from src.frontend.streamlit_app.pages._groups.cron.dashboard import render
from src.frontend.streamlit_app.shared.components import (
    related_pages_footer,
    require_auth,
    setup_page,
)

setup_page()
require_auth(label="admin")
st.header("📅 Панель Cron")
st.caption("Dashboard всех scheduled workflows с метриками и actions")
render()
related_pages_footer("14_Панель_Cron")
