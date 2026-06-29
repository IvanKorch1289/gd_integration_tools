"""Schema Admin — тонкий router для 3 tab'ов (S173 refactor).

Содержимое каждого tab'а вынесено в ``_groups/schema/{import,registry,viewer}_tab.py``.
"""

from __future__ import annotations

import streamlit as st

from src.frontend.streamlit_app.pages._groups.schema.import_tab import render_import_tab
from src.frontend.streamlit_app.pages._groups.schema.registry_tab import (
    render_registry_tab,
)
from src.frontend.streamlit_app.pages._groups.schema.viewer_tab import render_viewer_tab
from src.frontend.streamlit_app.shared.components import (
    related_pages_footer,
    setup_page,
)

setup_page()
st.header(":card_index_dividers: Админ схем")
st.caption("Единый раздел для управления схемами: импорт "
            "OpenAPI/Postman/WSDL, реестр схем, просмотр API-контрактов")

tab_import, tab_registry, tab_viewer = st.tabs(
    ["Импорт схемы", "Реестр схем", "API-схемы"]
)

with tab_import:
    render_import_tab()

with tab_registry:
    render_registry_tab()

with tab_viewer:
    render_viewer_tab()

related_pages_footer("62_Админ_схем")
