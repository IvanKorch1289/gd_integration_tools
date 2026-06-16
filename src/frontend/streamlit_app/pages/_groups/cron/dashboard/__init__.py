"""Per-page sub-package для ``14_Cron_Dashboard.py`` (S144 W4 TD-013 regrouping).

Streamlit page ``14_Cron_Dashboard.py`` (135 LOC, S12 K5 W3) — сводный
dashboard для всех scheduled workflows: таблица (name, cron_expr, tz,
last_run_at, next_run_at, success_rate(7d), status) + action кнопки
(Pause / Resume / Run now / Delete) + top-level metrics + auto-refresh
30 sec.

Логически один render-путь, но 135 LOC — borderline. Извлечено в
sub-package:

* :mod:`.render` — ``render()``: top-level entry, lazy streamlit import
  + setup_page + render_body (table + actions + metrics + auto-refresh).

**Pattern reference**: :mod:`src.frontend.streamlit_app.pages._groups.cron.builder`
(S144 W3, simpler 1-render-path pattern).

**Backward-compatible**: flat ``14_Cron_Dashboard.py`` остаётся
Streamlit-discoverable entry-point'ом, теперь thin wrapper, делегирующий
в :func:`render` ниже.

**Wave**: ``[wave:s144/w4-td013-cron-dashboard]``.
"""

from __future__ import annotations

from src.frontend.streamlit_app.pages._groups.cron.dashboard.render import render

__all__ = ("render",)
