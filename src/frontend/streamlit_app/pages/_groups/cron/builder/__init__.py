"""Per-page sub-package для ``13_Cron_Builder.py`` (S144 W3 TD-013 regrouping).

Streamlit page ``13_Cron_Builder.py`` (149 LOC, S12 K3 W2) — visual builder
для cron-выражений + live preview Next 5 executions + timezone-aware
(Europe/Moscow default) + dry-run simulation + Save в APScheduler
через admin_cron REST endpoint.

Логически независимых render-путей нет (single-mode page), но
149 LOC — borderline god-file per TD-013 (419+ LOC threshold). Извлечено
в этот sub-package:

* :mod:`.render` — ``render()``: top-level entry-point, lazy streamlit
  import + setup_page + render_body (mode radio + expression + preview +
  save + dry-run). Импортируется из thin ``13_Cron_Builder.py``.

**Pattern reference**: :mod:`src.frontend.streamlit_app.pages._groups.home.home_page`
(S142 W2 PoC, simpler 1-render-path pattern).

**Backward-compatible**: flat ``13_Cron_Builder.py`` остаётся
Streamlit-discoverable entry-point'ом, теперь thin wrapper, делегирующий
в :func:`render` ниже.

**Wave**: ``[wave:s144/w3-td013-cron-builder]``.
"""

from __future__ import annotations

from src.frontend.streamlit_app.pages._groups.cron.builder.render import render

__all__ = ("render",)
