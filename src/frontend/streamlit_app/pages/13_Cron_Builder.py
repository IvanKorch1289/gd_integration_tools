"""Cron Builder UI — Sprint 12 K3 W2.

Visual builder для cron-выражений + live preview ``Next 5 executions``
+ timezone-aware (Europe/Moscow по умолчанию) + dry-run simulation +
Save в APScheduler через admin_cron REST endpoint.

Два режима:
    * **Visual** — minute/hour/day/month/weekday dropdowns;
    * **Expression** — raw text input + validator.

Сохранение задачи отправляется POST /admin/cron/schedule.
"""

from __future__ import annotations

from datetime import datetime

import streamlit as st

from src.frontend.streamlit_app.api_clients import get_api_client
from src.frontend.streamlit_app.shared.components import setup_page

setup_page("Cron Builder", "")
st.header("Cron Builder — Sprint 12 K3 W2")
st.caption(
    "Постройте cron-выражение визуально или вручную, посмотрите Next 5 "
    "execution times в выбранном timezone, и зарегистрируйте задачу "
    "в APScheduler одним кликом."
)


def _supported_timezones() -> list[str]:
    try:
        from zoneinfo import available_timezones

        return sorted(available_timezones())
    except Exception:  # noqa: BLE001
        return ["Europe/Moscow", "UTC", "Europe/London", "America/New_York"]


tz_choices = _supported_timezones()
default_tz_idx = (
    tz_choices.index("Europe/Moscow") if "Europe/Moscow" in tz_choices else 0
)

mode = st.radio("Режим ввода", options=["Visual", "Expression"], horizontal=True)

if mode == "Visual":
    cols = st.columns(5)
    minute = cols[0].text_input("minute", value="0")
    hour = cols[1].text_input("hour", value="9")
    day = cols[2].text_input("day", value="*")
    month = cols[3].text_input("month", value="*")
    weekday = cols[4].text_input("weekday", value="1-5")
    expression = f"{minute} {hour} {day} {month} {weekday}"
else:
    expression = st.text_input(
        "Cron expression (5-field или 6-field с секундами)", value="0 9 * * 1-5"
    )

timezone = st.selectbox("Timezone", tz_choices, index=default_tz_idx)
preview_count = st.slider("Preview count", min_value=1, max_value=20, value=5)

st.code(expression, language="text")

client = get_api_client()

if st.button("Preview Next executions", type="primary"):
    try:
        resp = client._request(
            "POST",
            "/admin/cron/validate",
            json={
                "expression": expression,
                "timezone": timezone,
                "preview_count": preview_count,
            },
        )
        body = resp.json() if hasattr(resp, "json") else resp
    except AttributeError:
        # Fallback: api_client не имеет _request — собираем вручную через requests
        import httpx as requests

        base_url = getattr(client, "base_url", "http://localhost:8000")
        body = requests.post(
            f"{base_url}/api/v1/admin/cron/validate",
            json={
                "expression": expression,
                "timezone": timezone,
                "preview_count": preview_count,
            },
            timeout=5,
        ).json()
    except Exception as exc:  # noqa: BLE001
        st.error(f"Ошибка проверки выражения: {exc}")
        body = None

    if body:
        if body.get("is_valid"):
            st.success("Cron-выражение валидно")
            executions = body.get("next_executions", [])
            st.subheader("Next executions")
            for idx, dt_str in enumerate(executions, 1):
                try:
                    dt = datetime.fromisoformat(dt_str.replace("Z", "+00:00"))
                    weekday_name = dt.strftime("%A")
                    st.write(f"{idx}. **{dt.isoformat()}** ({weekday_name})")
                except (ValueError, AttributeError):
                    st.write(f"{idx}. {dt_str}")
        else:
            st.error(f"Невалидное выражение: {body.get('error', 'unknown')}")

st.divider()
st.subheader("Сохранение / dry-run")

with st.expander("Зарегистрировать задачу"):
    job_name = st.text_input("name (id)", value="my-cron-job")
    callable_ref = st.text_input(
        "callable_ref (module.path:function)",
        value="src.backend.infrastructure.scheduler.scheduled_tasks:check_all_services",
    )
    if st.button("Save"):
        try:
            import httpx as requests

            base_url = getattr(client, "base_url", "http://localhost:8000")
            resp = requests.post(
                f"{base_url}/api/v1/admin/cron/schedule",
                json={
                    "name": job_name,
                    "cron_expr": expression,
                    "callable_ref": callable_ref,
                    "timezone": timezone,
                },
                timeout=5,
            )
            if resp.status_code == 201:
                st.success(f"Задача {job_name!r} зарегистрирована")
            else:
                st.error(f"HTTP {resp.status_code}: {resp.text}")
        except Exception as exc:  # noqa: BLE001
            st.error(f"Ошибка регистрации: {exc}")

with st.expander("Dry-run (manage.py workflow dryrun)"):
    st.code(
        "python manage.py workflow dryrun --schedule '" + expression + "'",
        language="bash",
    )
    st.caption("Скопируйте команду и выполните в shell — proceeds без регистрации job.")
