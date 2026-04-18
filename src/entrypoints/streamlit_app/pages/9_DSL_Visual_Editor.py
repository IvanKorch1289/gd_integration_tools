"""DSL Visual Editor — конструктор pipeline без кода."""

import sys
from pathlib import Path

import streamlit as st

_root = Path(__file__).resolve().parents[4]
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

st.set_page_config(page_title="DSL Visual Editor", page_icon=":art:", layout="wide")
st.header("DSL Visual Editor")
st.caption("Собери маршрут из блоков — без кода. Экспорт в YAML/Python.")

# ─────────── Available processors ───────────

PROCESSORS = {
    "Basic": {
        "set_header": {"params": ["key", "value"]},
        "set_property": {"params": ["key", "value"]},
        "log": {"params": ["level"]},
        "validate": {"params": ["schema"]},
    },
    "Dispatch": {
        "dispatch_action": {"params": ["action"]},
        "enrich": {"params": ["action", "result_property"]},
    },
    "Transform": {
        "transform": {"params": ["expression"]},
        "filter": {"params": ["predicate"]},
        "translate": {"params": ["from_format", "to_format"]},
    },
    "Control Flow": {
        "retry": {"params": ["max_attempts", "delay_seconds"]},
        "choice": {"params": ["when", "otherwise"]},
        "parallel": {"params": ["branches", "strategy"]},
    },
    "AI": {
        "rag_search": {"params": ["query_field", "top_k"]},
        "compose_prompt": {"params": ["template", "context_property"]},
        "call_llm": {"params": ["provider", "model"]},
        "parse_llm_output": {"params": ["schema"]},
        "sanitize_pii": {"params": []},
        "restore_pii": {"params": []},
    },
    "Web": {
        "navigate": {"params": ["url"]},
        "click": {"params": ["url", "selector"]},
        "extract": {"params": ["selector", "output_property"]},
        "screenshot": {"params": ["url"]},
    },
    "Export": {
        "export": {"params": ["format", "title"]},
    },
}

# ─────────── Session state ───────────

if "pipeline_steps" not in st.session_state:
    st.session_state.pipeline_steps = []
if "route_id" not in st.session_state:
    st.session_state.route_id = "my_route"
if "source" not in st.session_state:
    st.session_state.source = "internal:my_source"

# ─────────── Layout ───────────

col1, col2 = st.columns([1, 2])

with col1:
    st.subheader("Конфигурация")
    st.session_state.route_id = st.text_input("Route ID", value=st.session_state.route_id)
    st.session_state.source = st.text_input("Source", value=st.session_state.source)

    st.divider()
    st.subheader("Добавить процессор")
    category = st.selectbox("Категория", list(PROCESSORS.keys()))
    processor = st.selectbox("Процессор", list(PROCESSORS[category].keys()))
    params = PROCESSORS[category][processor]["params"]

    param_values = {}
    with st.expander("Параметры"):
        for p in params:
            param_values[p] = st.text_input(f"{p}", key=f"param_{processor}_{p}")

    if st.button("+ Добавить"):
        st.session_state.pipeline_steps.append({
            "type": processor,
            "params": {k: v for k, v in param_values.items() if v},
        })
        st.rerun()

with col2:
    st.subheader("Pipeline")
    if not st.session_state.pipeline_steps:
        st.info("Добавьте процессоры слева")
    else:
        for i, step in enumerate(st.session_state.pipeline_steps):
            with st.container():
                c1, c2 = st.columns([5, 1])
                with c1:
                    st.markdown(f"**{i+1}. {step['type']}**")
                    if step["params"]:
                        st.caption(", ".join(f"{k}={v}" for k, v in step["params"].items()))
                with c2:
                    if st.button("✕", key=f"del_{i}"):
                        st.session_state.pipeline_steps.pop(i)
                        st.rerun()

    if st.button("Очистить всё"):
        st.session_state.pipeline_steps = []
        st.rerun()

# ─────────── Export ───────────

st.divider()
st.subheader("Экспорт")

tab_yaml, tab_python = st.tabs(["YAML", "Python"])

with tab_yaml:
    yaml_lines = [
        f"route_id: {st.session_state.route_id}",
        f"source: {st.session_state.source}",
        "processors:",
    ]
    for step in st.session_state.pipeline_steps:
        yaml_lines.append(f"  - type: {step['type']}")
        for k, v in step["params"].items():
            yaml_lines.append(f"    {k}: {v}")
    st.code("\n".join(yaml_lines), language="yaml")
    st.download_button("Скачать .dsl.yaml", "\n".join(yaml_lines), f"{st.session_state.route_id}.dsl.yaml")

with tab_python:
    py_lines = [
        "from app.dsl.builder import RouteBuilder",
        "",
        "route = (",
        f"    RouteBuilder.from_(\"{st.session_state.route_id}\", source=\"{st.session_state.source}\")",
    ]
    for step in st.session_state.pipeline_steps:
        args = ", ".join(f'{k}="{v}"' for k, v in step["params"].items())
        py_lines.append(f"    .{step['type']}({args})")
    py_lines.append("    .build()")
    py_lines.append(")")
    code = "\n".join(py_lines)
    st.code(code, language="python")
    st.download_button("Скачать route.py", code, f"{st.session_state.route_id}.py")
