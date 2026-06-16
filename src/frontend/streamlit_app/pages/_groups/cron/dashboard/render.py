"""Render logic для ``14_Cron_Dashboard`` (S144 W4 extraction).

Cron Schedule Dashboard — Sprint 12 K5 W3.

Сводный dashboard для всех scheduled workflows:

* Таблица: name, cron_expr, tz, last_run_at, next_run_at, success_rate(7d),
  status (enabled/paused).
* Action кнопки per row: Pause / Resume / Run now / Delete.
* Top-level metrics: total scheduled / today runs / today failed.
* Auto-refresh каждые 30 сек.

Извлечено из ``14_Cron_Dashboard.py`` (135 LOC → split):
* ``render()`` — top-level entry, lazy streamlit import + setup_page.
"""

from __future__ import annotations


def _render_body() -> None:
    """Render page body (called after setup_page from render())."""
    # Lazy imports — keeps the module import-safe in test envs
    # without [frontend] extra (see TD-013 pilot contract).
    import streamlit as st

    try:
        import streamlit_autorefresh

        streamlit_autorefresh.st_autorefresh(
            interval=30_000, key="cron_dashboard_refresh"
        )
    except ImportError:
        pass

    import asyncio

    from src.frontend.streamlit_app.api_clients import get_api_client

    client = get_api_client()

    try:
        rows = (
            asyncio.run(client.list_schedules())
            if hasattr(client, "list_schedules")
            else []
        )
    except Exception as exc:  # noqa: BLE001
        st.error(f"Не удалось получить список schedules: {exc}")
        rows = []

    if not rows:
        st.info(
            "Нет scheduled workflows. Создайте через 13_Cron_Builder или manage.py."
        )
        return

    # Top-level metrics
    total = len(rows)
    enabled = sum(1 for r in rows if r.get("status") == "enabled")
    today_runs = sum(r.get("today_runs", 0) for r in rows)
    today_failed = sum(r.get("today_failed", 0) for r in rows)

    cols = st.columns(4)
    cols[0].metric("Total scheduled", total)
    cols[1].metric("Enabled", enabled)
    cols[2].metric("Today runs", today_runs)
    cols[3].metric("Today failed", today_failed)

    st.divider()

    # Schedule table + actions per row
    for row in rows:
        name = row.get("name", "?")
        with st.expander(
            f"⏰ {name} — {row.get('cron_expr', '?')} ({row.get('tz', 'UTC')})"
        ):
            st.write(
                {
                    "Name": name,
                    "Cron": row.get("cron_expr", "?"),
                    "TZ": row.get("tz", "UTC"),
                    "Last run": row.get("last_run_at", "—"),
                    "Next run": row.get("next_run_at", "—"),
                    "Success rate (7d)": f"{row.get('success_rate_7d', 0) * 100:.1f}%",
                    "Status": row.get("status", "unknown"),
                }
            )
            action_cols = st.columns(4)
            if action_cols[0].button("Pause", key=f"pause_{name}"):
                try:
                    asyncio.run(client.pause_schedule(name)) if hasattr(
                        client, "pause_schedule"
                    ) else None
                    st.success(f"Paused {name}")
                except Exception as exc:  # noqa: BLE001
                    st.error(f"Ошибка pause: {exc}")
            if action_cols[1].button("Resume", key=f"resume_{name}"):
                try:
                    asyncio.run(client.resume_schedule(name)) if hasattr(
                        client, "resume_schedule"
                    ) else None
                    st.success(f"Resumed {name}")
                except Exception as exc:  # noqa: BLE001
                    st.error(f"Ошибка resume: {exc}")
            if action_cols[2].button("Run now", key=f"run_{name}"):
                try:
                    asyncio.run(client.run_schedule_now(name)) if hasattr(
                        client, "run_schedule_now"
                    ) else None
                    st.success(f"Triggered {name}")
                except Exception as exc:  # noqa: BLE001
                    st.error(f"Ошибка run-now: {exc}")
            if action_cols[3].button("Delete", key=f"delete_{name}"):
                try:
                    asyncio.run(client.delete_schedule(name)) if hasattr(
                        client, "delete_schedule"
                    ) else None
                    st.success(f"Deleted {name}")
                except Exception as exc:  # noqa: BLE001
                    st.error(f"Ошибка delete: {exc}")


def render() -> None:
    """Top-level entry-point, вызывается из thin ``14_Cron_Dashboard.py``.

    Инициализирует streamlit page и рендерит body. Back-compat semantics
    with original page logic.
    """
    # Lazy streamlit import — keeps the module import-safe in test envs
    # without [frontend] extra (see TD-013 pilot contract).
    import streamlit as st

    from src.frontend.streamlit_app.shared.components import setup_page

    setup_page("Cron Dashboard", "")
    st.header("Cron Schedule Dashboard — Sprint 12 K5 W3")
    st.caption(
        "Все scheduled workflows: cron-expr, next/last run, success rate (7d). "
        "Auto-refresh каждые 30 секунд."
    )
    _render_body()
