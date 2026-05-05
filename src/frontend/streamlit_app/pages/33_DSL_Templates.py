"""DSL Templates — каталог шаблонов маршрутов.

Источник — :mod:`app.dsl.templates_library`: именованные builder'ы с параметрами.
Страница рендерит шаблон → генерирует YAML → позволяет скопировать.
"""

from __future__ import annotations

import sys
from pathlib import Path

import streamlit as st

_root = Path(__file__).resolve().parents[4]
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

from src.entrypoints.streamlit_app.api_client import get_api_client

st.set_page_config(page_title="Templates", page_icon=":scroll:", layout="wide")
st.header(":scroll: DSL Templates")

client = get_api_client()

try:
    templates = client._request("GET", "/api/v1/admin/templates")  # type: ignore[attr-defined]
    if not isinstance(templates, list):
        templates = []
except Exception as exc:  # noqa: BLE001
    templates = []
    st.warning(f"Каталог шаблонов недоступен: {exc}")

if not templates:
    st.info(
        "Шаблоны берутся из `src/dsl/templates_library.py`. "
        "Backend должен экспонировать `GET /api/v1/admin/templates`."
    )
else:
    for tpl in templates:
        name = tpl.get("name", "—")
        descr = tpl.get("description", "")
        with st.expander(f"{name}"):
            st.caption(descr)
            params = tpl.get("params", {})
            if params:
                st.write("**Параметры:**")
                st.json(params)
            yaml_content = tpl.get("yaml", "")
            if yaml_content:
                st.code(yaml_content, language="yaml")
            if st.button("Инстанциировать", key=f"inst_{name}"):
                try:
                    resp = client._request(  # type: ignore[attr-defined]
                        "POST", f"/api/v1/admin/templates/{name}/instantiate", json={}
                    )
                    st.success(f"Создан route: {resp}")
                except Exception as exc:  # noqa: BLE001
                    st.error(str(exc))
