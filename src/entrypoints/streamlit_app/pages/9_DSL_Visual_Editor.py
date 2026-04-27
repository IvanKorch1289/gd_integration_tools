"""DSL Visual Editor — простой конструктор."""

import streamlit as st

st.set_page_config(page_title="DSL Editor", layout="wide")
st.header("DSL Visual Editor")
st.caption("Соберите маршрут из процессоров. Экспорт в YAML / Python.")

# Процессоры: тип → список параметров
PROCESSORS = {
    "dispatch_action": ["action"],
    "validate": ["schema"],
    "transform": ["expression"],
    "log": ["level"],
    "retry": ["max_attempts"],
    "rag_search": ["query_field", "top_k"],
    "call_llm": ["provider"],
    "sanitize_pii": [],
    "restore_pii": [],
    "navigate": ["url"],
    "extract": ["selector"],
    "export": ["format"],
    "notify": ["channel", "to"],
}

if "steps" not in st.session_state:
    st.session_state.steps = []

col1, col2 = st.columns([1, 2])

with col1:
    route_id = st.text_input("Route ID", value="my.route")
    source = st.text_input("Source", value="internal:my")

    st.divider()
    proc_type = st.selectbox("Процессор", list(PROCESSORS.keys()))
    params = {}
    for p in PROCESSORS[proc_type]:
        params[p] = st.text_input(p, key=f"p_{proc_type}_{p}")

    if st.button("+ Добавить", use_container_width=True):
        st.session_state.steps.append(
            {"type": proc_type, "params": {k: v for k, v in params.items() if v}}
        )

    if st.button("Очистить", use_container_width=True):
        st.session_state.steps = []

with col2:
    st.subheader("Pipeline")
    for i, s in enumerate(st.session_state.steps):
        c1, c2 = st.columns([5, 1])
        c1.write(
            f"{i + 1}. **{s['type']}** "
            + ", ".join(f"{k}={v}" for k, v in s["params"].items())
        )
        if c2.button("✕", key=f"d_{i}"):
            st.session_state.steps.pop(i)
            st.rerun()

    if st.session_state.steps:
        st.divider()
        tab_yaml, tab_py = st.tabs(["YAML", "Python"])
        with tab_yaml:
            yaml_out = f"route_id: {route_id}\nsource: {source}\nprocessors:\n"
            for s in st.session_state.steps:
                yaml_out += f"  - type: {s['type']}\n"
                for k, v in s["params"].items():
                    yaml_out += f"    {k}: {v}\n"
            st.code(yaml_out, language="yaml")
        with tab_py:
            py_out = f'RouteBuilder.from_("{route_id}", source="{source}")'
            for s in st.session_state.steps:
                args = ", ".join(f'{k}="{v}"' for k, v in s["params"].items())
                py_out += f"\n    .{s['type']}({args})"
            py_out += "\n    .build()"
            st.code(py_out, language="python")
