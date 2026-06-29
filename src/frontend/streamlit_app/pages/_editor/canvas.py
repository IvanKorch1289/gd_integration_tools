"""Drag-drop pipeline canvas renderer (S84 W3 C1 extraction).

Бывший ``_render_drag_drop_pipeline()`` из 31_DSL_Visual_Editor.py.
"""

from __future__ import annotations

import streamlit as st


def render_drag_drop_pipeline(steps: list[dict], meta: dict) -> list[dict] | None:
    """Render the pipeline with drag-drop reordering using HTML/JS interop.

    Returns the reordered steps list if changed, otherwise None.
    """
    import json

    steps_json = json.dumps(steps)

    html = f"""
    <style>
    .pipeline-container {{
        font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
    }}
    .pipeline-item {{
        background: linear-gradient(135deg, #1a1a2e 0%, #16213e 100%);
        border: 1px solid #0f3460;
        border-radius: 8px;
        padding: 12px 16px;
        margin: 8px 0;
        cursor: grab;
        transition: all 0.2s;
        display: flex;
        align-items: center;
        gap: 12px;
    }}
    .pipeline-item:hover {{
        background: linear-gradient(135deg, #1f1f3a 0%, #1a2744 100%);
        border-color: #7dd3fc;
        transform: translateX(4px);
    }}
    .pipeline-item.dragging {{
        opacity: 0.5;
        transform: scale(1.02);
    }}
    .pipeline-item .handle {{
        color: #7dd3fc;
        font-size: 18px;
        cursor: grab;
    }}
    .pipeline-item .step-num {{
        background: #7dd3fc;
        color: #1a1a2e;
        width: 24px;
        height: 24px;
        border-radius: 50%;
        display: flex;
        align-items: center;
        justify-content: center;
        font-weight: 700;
        font-size: 12px;
        flex-shrink: 0;
    }}
    .pipeline-item .step-content {{
        flex: 1;
    }}
    .pipeline-item .step-type {{
        font-weight: 600;
        color: #7dd3fc;
        font-size: 14px;
    }}
    .pipeline-item .step-params {{
        font-size: 11px;
        color: #a0a0a0;
        margin-top: 2px;
    }}
    .pipeline-empty {{
        text-align: center;
        padding: 40px;
        color: #6b7280;
        border: 2px dashed #374151;
        border-radius: 8px;
        margin: 16px 0;
    }}
    .drop-zone {{
        min-height: 60px;
        border: 2px dashed #374151;
        border-radius: 8px;
        padding: 8px;
        transition: border-color 0.2s, background 0.2s;
    }}
    .drop-zone.drag-over {{
        border-color: #7dd3fc;
        background: rgba(125, 211, 252, 0.1);
    }}
    </style>

    <div class="pipeline-container">
        <div id="drop-zone" class="drop-zone">
            <div id="pipeline-list">
            </div>
        </div>
        <div id="empty-msg" class="pipeline-empty" style="display: none;">
            �_empty_placeholder😐 Перетащите процессор из палитры или
            добавьте через форму слева
        </div>
    </div>

    <script>
    const stepsData = {steps_json};

    function renderSteps(steps) {{
        const list = document.getElementById('pipeline-list');
        const emptyMsg = document.getElementById('empty-msg');
        const dropZone = document.getElementById('drop-zone');

        if (!steps || steps.length === 0) {{
            list.innerHTML = '';
            emptyMsg.style.display = 'block';
            dropZone.style.display = 'block';
            return;
        }}

        emptyMsg.style.display = 'none';
        list.innerHTML = steps.map((step, i) => `
            <div class="pipeline-item" draggable="true" data-index="${{i}}">
                <span class="handle">☰</span>
                <span class="step-num">${{i + 1}}</span>
                <div class="step-content">
                    <div class="step-type">▶ ${{step.type}}</div>
                    <div class="step-params">${{
                        Object.keys(step.params || {{}}).length > 0
                            ? Object.entries(step.params || {{}}).map(
                                ([k,v]) => `${{k}}=${{v}}`
                            ).join(', ')
                            : 'без параметров'
                    }}</div>
                </div>
            </div>
        `).join('');

        // Attach drag events
        const items = list.querySelectorAll('.pipeline-item');
        items.forEach(item => {{
            item.addEventListener('dragstart', handleDragStart);
            item.addEventListener('dragend', handleDragEnd);
        }});

        dropZone.style.display = 'block';
    }}

    let draggedIndex = null;

    function handleDragStart(e) {{
        draggedIndex = parseInt(e.target.dataset.index);
        e.target.classList.add('dragging');
        e.dataTransfer.setData('text/plain', e.target.dataset.index);
        e.dataTransfer.effectAllowed = 'move';
    }}

    function handleDragEnd(e) {{
        e.target.classList.remove('dragging');
        draggedIndex = null;
        // Remove drag-over from all zones
        document.querySelectorAll('.drag-over').forEach(
            el => el.classList.remove('drag-over')
        );
    }}

    // Drop zone events
    const dropZone = document.getElementById('drop-zone');
    dropZone.addEventListener('dragover', (e) => {{
        e.preventDefault();
        e.dataTransfer.dropEffect = 'move';
        dropZone.classList.add('drag-over');
    }});
    dropZone.addEventListener('dragleave', () => {{
        dropZone.classList.remove('drag-over');
    }});
    dropZone.addEventListener('drop', (e) => {{
        e.preventDefault();
        dropZone.classList.remove('drag-over');

        const fromIndex = parseInt(e.dataTransfer.getData('text/plain'));
        const toIndex = draggedIndex;

        if (!isNaN(fromIndex) && fromIndex !== toIndex) {{
            // Reorder steps
            const newSteps = [...stepsData];
            const [moved] = newSteps.splice(fromIndex, 1);
            newSteps.splice(toIndex, 0, moved);

            // Dispatch custom event for Streamlit
            const event = new CustomEvent('reorder-steps', {{
                detail: {{ steps: newSteps }},
                bubbles: true
            }});
            window.parent.document.dispatchEvent(event);
        }}
    }});

    // Handle reordering within the list
    function handleDragOver(e) {{
        e.preventDefault();
        e.dataTransfer.dropEffect = 'move';
    }}

    renderSteps(stepsData);
    </script>
    """

    st.components.v1.html(html, height=max(200, len(steps) * 70 + 80), scrolling=False)

    # Handle reorder events via JavaScript interop using a hidden element
    # We use query_params to communicate the new order
    st.markdown(
        """
    <script>
    window.addEventListener('message', function(e) {
        if (e.data && e.data.type === 'reorder-steps') {
            const params = new URLSearchParams();
            params.set('reorder', JSON.stringify(e.data.steps));
            window.parent.location.search = params.toString();
        }
    });
    </script>
    """,
        unsafe_allow_html=True,
    )

    return None
