"""Prompt Lab — A/B prompt versioning (Sprint 9 K4 W4 / GAP-AI-3.2).

Управление версиями prompt'ов, A/B-сравнение, rollback.
LangFuse 3.x backend — staging rollout S10.

Feature-flag: ``feature_flags.prompt_lab_enabled`` (default-OFF).
"""

from __future__ import annotations

import json
import sys

import streamlit as st


from src.frontend.streamlit_app.api_client import get_api_client

st.set_page_config(page_title="Prompt Lab", page_icon=":test_tube:", layout="wide")
st.header(":test_tube: Prompt Lab — A/B versioning")

client = get_api_client()

tab_list, tab_compare, tab_create = st.tabs(
    [":mag: Browse prompts", ":bar_chart: A/B Compare", ":pencil2: Create version"]
)


with tab_list:
    try:
        names_response = client.get("/admin/prompt-versions")
        names_response.raise_for_status()
        names = names_response.json().get("items", [])
    except Exception as exc:  # noqa: BLE001
        st.error(f"Failed to fetch prompt names: {exc}")
        names = []

    selected_name = st.selectbox("Prompt name", options=[""] + names, key="prompt-name")
    if selected_name:
        try:
            versions_resp = client.get(f"/admin/prompt-versions/{selected_name}")
            versions_resp.raise_for_status()
            versions = versions_resp.json().get("items", [])
        except Exception as exc:  # noqa: BLE001
            st.error(f"Failed to fetch versions: {exc}")
            versions = []

        for ver in versions:
            badge = ":green_circle: ACTIVE" if ver["is_active"] else ":white_circle:"
            with st.expander(
                f"{badge} v{ver['version']} — {ver['model']} "
                f"(created {ver['created_at'][:19]})",
                expanded=ver["is_active"],
            ):
                col_a, col_b = st.columns([2, 1])
                with col_a:
                    st.code(ver["body"], language="text")
                with col_b:
                    st.json(ver["parameters"], expanded=False)
                    st.metric("Accuracy", ver["metrics"].get("accuracy", "—"))
                    st.metric(
                        "p95 latency, ms", ver["metrics"].get("p95_latency_ms", "—")
                    )
                    st.metric("Cost USD/1k", ver["metrics"].get("cost_usd_per_1k", "—"))
                    if not ver["is_active"] and st.button(
                        f"Activate v{ver['version']}", key=f"act-{ver['version']}"
                    ):
                        try:
                            client.post(
                                f"/admin/prompt-versions/{selected_name}/activate",
                                json={"version": ver["version"]},
                            ).raise_for_status()
                            st.success(f"Activated v{ver['version']}")
                            st.rerun()
                        except Exception as exc:  # noqa: BLE001
                            st.error(f"Activate failed: {exc}")


with tab_compare:
    st.subheader("A/B сравнение версий")
    compare_name = st.text_input("Prompt name", key="compare-name")
    col_va, col_vb = st.columns(2)
    version_a = col_va.number_input("Version A", min_value=1, value=1)
    version_b = col_vb.number_input("Version B", min_value=1, value=2)
    if st.button("Compare") and compare_name:
        try:
            resp = client.get(
                f"/admin/prompt-versions/{compare_name}/compare",
                params={"a": int(version_a), "b": int(version_b)},
            )
            resp.raise_for_status()
            data = resp.json()
            st.subheader("Metric diffs (B − A)")
            for metric, diff in data.get("metric_diffs", {}).items():
                color = ":green_circle:" if diff < 0 else ":red_circle:"
                st.metric(metric, f"{diff:+.4f}", delta_color="inverse")
                st.write(f"{color} {metric}")
            with st.expander("Raw comparison"):
                st.json(data)
        except Exception as exc:  # noqa: BLE001
            st.error(f"Compare failed: {exc}")


with tab_create:
    st.subheader("Create new version")
    new_name = st.text_input("Prompt name (existing or new)", key="new-name")
    new_body = st.text_area("Prompt body", height=200, key="new-body")
    new_model = st.text_input("Model", value="gpt-4o-mini", key="new-model")
    new_params_raw = st.text_area(
        "Parameters JSON", value='{"temperature": 0.0, "top_p": 1.0}', height=80
    )
    new_author = st.text_input("Author (your name)", key="new-author")
    if st.button("Create"):
        try:
            params_dict = json.loads(new_params_raw or "{}")
        except json.JSONDecodeError as exc:
            st.error(f"Invalid JSON: {exc}")
            params_dict = None
        if params_dict is not None and new_name and new_body:
            try:
                resp = client.post(
                    "/admin/prompt-versions",
                    json={
                        "name": new_name,
                        "body": new_body,
                        "model": new_model,
                        "parameters": params_dict,
                        "created_by": new_author or None,
                    },
                )
                resp.raise_for_status()
                created = resp.json()
                st.success(f"Created {created['name']}:v{created['version']}")
                st.json(created)
            except Exception as exc:  # noqa: BLE001
                st.error(f"Create failed: {exc}")
