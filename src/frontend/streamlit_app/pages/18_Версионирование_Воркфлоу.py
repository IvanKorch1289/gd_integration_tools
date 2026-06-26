"""Workflow Versioning UI — Sprint 12 K3 W8.

UI для WorkflowVersionRegistry: pin default + rollback + history view.

Источник правды: ``WorkflowVersionRegistry`` через
``/api/v1/admin/workflow-versioning``.
"""

from __future__ import annotations

import streamlit as st

from src.frontend.streamlit_app.shared.components import require_auth, setup_page

setup_page()
require_auth(label="write action")
st.header("Версионирование Workflow")
st.caption(
    "Управление WorkflowVersionRegistry: pin default / rollback / "
    "running executions counter."
)


try:
    from src.backend.services.dsl_portal import get_global_registry

    registry = get_global_registry()
    all_ids = sorted(registry.all_workflow_ids())
except Exception as exc:  # noqa: BLE001
    all_ids = []
    st.warning(f"Registry недоступен: {exc}")


if not all_ids:
    st.info("Реестр пуст. Зарегистрируйте workflow через @workflow_versioned('X.Y.Z').")
else:
    selected = st.selectbox("ID Воркфлоу", all_ids)
    history = registry.history(selected)

    st.subheader(f"История {selected!r}")
    if not history:
        st.write("(пусто)")
    else:
        for v in history:
            marker = "🟢 default" if v.default_version else ""
            cols = st.columns([3, 1, 1])
            cols[0].write(f"**v{v.semver}** {marker}")
            if not v.default_version:
                if cols[1].button("Сделать default", key=f"pin_{v.semver}"):
                    try:
                        import httpx as requests

                        from src.frontend.streamlit_app.api_clients import (
                            get_api_client,
                        )

                        client = get_api_client()
                        base_url = getattr(client, "base_url", "http://localhost:8000")
                        resp = requests.post(
                            f"{base_url}/api/v1/admin/workflow-versioning/"
                            f"{selected}/pin",
                            params={"semver": v.semver},
                            timeout=5,
                        )
                        if resp.status_code == 200:
                            st.success(f"v{v.semver} закреплена как default")
                            st.rerun()
                        else:
                            st.error(f"HTTP {resp.status_code}: {resp.text}")
                    except Exception as exc:  # noqa: BLE001
                        st.error(f"Ошибка закрепления: {exc}")
            else:
                cols[1].write("")
            cols[2].write(f"major={v.major}")

        if len(history) >= 2:
            st.divider()
            if st.button("Откатить на предыдущую версию", type="primary"):
                try:
                    import httpx as requests

                    from src.frontend.streamlit_app.api_clients import get_api_client

                    client = get_api_client()
                    base_url = getattr(client, "base_url", "http://localhost:8000")
                    resp = requests.post(
                        f"{base_url}/api/v1/admin/workflow-versioning/"
                        f"{selected}/rollback",
                        timeout=5,
                    )
                    if resp.status_code == 200:
                        body = resp.json()
                        st.success(
                            f"Откат выполнен. Новый default: "
                            f"v{body['new_default']['semver']}"
                        )
                        st.rerun()
                    else:
                        st.error(f"HTTP {resp.status_code}: {resp.text}")
                except Exception as exc:  # noqa: BLE001
                    st.error(f"Ошибка отката: {exc}")

    st.divider()
    st.subheader("Запущенные исполнения по версиям")
    try:
        import httpx as requests

        from src.frontend.streamlit_app.api_clients import get_api_client

        client = get_api_client()
        base_url = getattr(client, "base_url", "http://localhost:8000")
        resp = requests.get(
            f"{base_url}/api/v1/admin/workflow-versioning/{selected}/running-count",
            timeout=5,
        )
        if resp.status_code == 200:
            counts = resp.json().get("counts", {})
            if counts:
                st.bar_chart(counts)
            else:
                st.info(
                    "Нет running executions или Temporal Client не поддерживает "
                    "count_running_per_version."
                )
    except Exception as exc:  # noqa: BLE001
        st.warning(f"Счётчик запущенных недоступен: {exc}")
