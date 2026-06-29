"""Step palette renderer (S84 W3 C1 extraction).

Бывший ``_render_step_palette()`` из 31_DSL_Visual_Editor.py.
"""

from __future__ import annotations

import streamlit as st

from src.frontend.streamlit_app.pages._editor.constants import STEP_PALETTE


def render_step_palette():
    """Render draggable step palette items using HTML/JS."""
    html = """
    <style>
    .step-palette-item {
        background: #2b3a4a;
        border: 1px solid #4a5a6a;
        border-radius: 6px;
        padding: 8px 12px;
        margin: 4px 0;
        cursor: grab;
        color: #e0e0e0;
        font-size: 13px;
        transition: background 0.2s, transform 0.1s;
        user-select: none;
    }
    .step-palette-item:hover {
        background: #3a4a5a;
        transform: translateX(4px);
    }
    .step-palette-item:active {
        cursor: grabbing;
    }
    .step-palette-item .title {
        font-weight: 600;
        color: #7dd3fc;
    }
    .step-palette-item .desc {
        font-size: 11px;
        color: #a0a0a0;
        margin-top: 2px;
    }
    .palette-header {
        font-size: 14px;
        font-weight: 600;
        color: #f0f0f0;
        margin-bottom: 8px;
    }
    </style>
    <div class="palette-header">📦 Step Palette (drag to add)</div>
    <div id="palette-container">
    """
    for key, info in STEP_PALETTE.items():
        html += f"""
        <div class="step-palette-item" draggable="true" data-processor="{key}">
            <div class="title">▶ {info["title"]}</div>
            <div class="desc">{info["desc"]}</div>
        </div>
        """
    html += """
    </div>
    <script>
    const items = document.querySelectorAll('.step-palette-item');
    let draggedItem = null;

    items.forEach(item => {
        item.addEventListener('dragstart', (e) => {
            draggedItem = item;
            item.style.opacity = '0.5';
            e.dataTransfer.setData('text/plain', item.dataset.processor);
        });
        item.addEventListener('dragend', () => {
            item.style.opacity = '1';
            draggedItem = null;
        });
    });
    </script>
    """

    st.sidebar.markdown("---")
    st.sidebar.subheader("📦 Палитра шагов")
    st.sidebar.markdown(
        "Перетащите процессор в область конвейера ниже,"
        " или нажмите чтобы добавить:"
    )
    st.components.v1.html(html, height=400, scrolling=True)

    # Show clickable buttons as alternative to drag
    selected_palette_proc = st.sidebar.selectbox(
        "Или выберите процессор:",
        ["—"] + list(STEP_PALETTE.keys()),
        key="palette_select",
    )
    if selected_palette_proc != "—":
        st.sidebar.info(
            (
            f"➡️ Перетащите **{selected_palette_proc}** на панель Pipeline ниже "
            f"или добавьте через форму слева."
        )
        )
        # Auto-select in the visual editor form
        st.session_state.vis_proc_type = selected_palette_proc
