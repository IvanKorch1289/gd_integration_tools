"""Prompt Lab — A/B prompt versioning (Sprint 9 K4 W4 / GAP-AI-3.2).

Управление версиями prompt'ов, A/B-сравнение, rollback.
LangFuse 3.x backend — staging rollout S10.

Feature-flag: ``feature_flags.prompt_lab_enabled`` (default-OFF).
"""

from __future__ import annotations

import json

import streamlit as st

from src.frontend.streamlit_app.api_clients import get_api_client
from src.frontend.streamlit_app.shared.components import (
    related_pages_footer,
    require_auth,
    setup_page,
)

setup_page()
require_auth(label="write action")
st.header(":test_tube: Prompt Lab — A/B версионирование")
st.caption(
    "Управление версиями prompt'ов, A/B-сравнение, rollback. "
    "LangFuse 3.x backend (staging rollout)."
)

client = get_api_client()

tab_list, tab_compare, tab_create = st.tabs(
    [
        ":mag: Просмотр prompt'ов",
        ":bar_chart: A/B Сравнение",
        ":pencil2: Создать версию",
    ]
)


with tab_list:
    st.info(
        "Prompt Lab недоступен: серверные endpoint'ы "
        "`/api/v1/admin/prompt-versions*` не реализованы (ADR-0425)."
    )
    names: list[str] = []

    selected_name = st.selectbox(
        "Имя prompt'а", options=[""] + names, key="prompt-name"
    )
    if selected_name:
        st.info("Список версий недоступен: endpoint не реализован (ADR-0425).")
        versions: list[dict[str, object]] = []

        for ver in versions:
            badge = ":green_circle: АКТИВНАЯ" if ver["is_active"] else ":white_circle:"
            with st.expander(
                f"{badge} v{ver['version']} — {ver['model']} "
                f"(создана {ver['created_at'][:19]})",
                expanded=ver["is_active"],
            ):
                col_a, col_b = st.columns([2, 1])
                with col_a:
                    st.code(ver["body"], language="text")
                with col_b:
                    st.json(ver["parameters"], expanded=False)
                    st.metric("Точность", ver["metrics"].get("accuracy", "—"))
                    st.metric(
                        "p95 латентность, мс", ver["metrics"].get("p95_latency_ms", "—")
                    )
                    st.metric(
                        "Стоимость USD/1k", ver["metrics"].get("cost_usd_per_1k", "—")
                    )
                    st.caption(
                        "Активация версии недоступна: endpoint не реализован "
                        "(ADR-0425)."
                    )


with tab_compare:
    st.subheader("A/B сравнение версий")
    compare_name = st.text_input("Имя prompt'а", key="compare-name")
    col_va, col_vb = st.columns(2)
    version_a = col_va.number_input("Версия A", min_value=1, value=1)
    version_b = col_vb.number_input("Версия B", min_value=1, value=2)
    if st.button("Сравнить") and compare_name:
        st.info(
            "A/B-сравнение недоступно: серверный endpoint не реализован (ADR-0425)."
        )


with tab_create:
    st.subheader("Создать новую версию")
    new_name = st.text_input("Имя prompt'а (существующий или новый)", key="new-name")
    new_body = st.text_area("Тело prompt'а", height=200, key="new-body")
    new_model = st.text_input("Модель", value="gpt-4o-mini", key="new-model")
    new_params_raw = st.text_area(
        "Параметры (JSON)", value='{"temperature": 0.0, "top_p": 1.0}', height=80
    )
    new_author = st.text_input("Автор (ваше имя)", key="new-author")
    if st.button("Создать"):
        try:
            params_dict = json.loads(new_params_raw or "{}")
        except json.JSONDecodeError as exc:
            st.error(f"Некорректный JSON: {exc}")
            params_dict = None
        if params_dict is not None and new_name and new_body:
            st.info(
                "Создание версии недоступно: серверный endpoint не реализован "
                "(ADR-0425)."
            )

related_pages_footer("48_Лаборатория_промптов")
