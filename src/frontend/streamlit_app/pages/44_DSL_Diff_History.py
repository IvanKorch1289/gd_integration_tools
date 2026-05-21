"""DSL Diff History — visual diff между версиями DSL route (S10 K3 W6)."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import streamlit as st
import yaml as _yaml

_root = Path(__file__).resolve().parents[4]
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))


def _load_diff_module():
    path = _root / "tools" / "dsl_diff.py"
    spec = importlib.util.spec_from_file_location("_dsl_diff_app", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


_diff_mod = _load_diff_module()

st.set_page_config(page_title="DSL Diff History", page_icon=":scroll:", layout="wide")
st.header("DSL Diff History")
st.caption("Sprint 10 K3 W6: side-by-side diff двух версий route.")

col1, col2 = st.columns(2)
with col1:
    st.subheader("Before")
    before_text = st.text_area("YAML 'before'", height=400, key="before_yaml")
with col2:
    st.subheader("After")
    after_text = st.text_area("YAML 'after'", height=400, key="after_yaml")

if st.button("Сравнить", type="primary"):
    if not before_text or not after_text:
        st.warning("Заполните оба поля для сравнения.")
    else:
        try:
            before = _yaml.safe_load(before_text) or {}
            after = _yaml.safe_load(after_text) or {}
        except _yaml.YAMLError as exc:
            st.error(f"YAML parse error: {exc}")
            st.stop()

        diff = _diff_mod._diff_pipelines(before, after)
        identical = not (diff["added"] or diff["removed"] or diff["changed"])

        if identical:
            st.success("Pipeline идентичен.")
        else:
            st.markdown(
                f"**route_id**: `{diff['route_id_before']}` → "
                f"`{diff['route_id_after']}`"
            )
            if diff["added"]:
                st.markdown(":green[**Добавлено:**]")
                for item in diff["added"]:
                    st.code(f"+ [{item['index']}] {item['step']}", language="yaml")
            if diff["removed"]:
                st.markdown(":red[**Удалено:**]")
                for item in diff["removed"]:
                    st.code(f"- [{item['index']}] {item['step']}", language="yaml")
            if diff["changed"]:
                st.markdown(":orange[**Изменено:**]")
                for item in diff["changed"]:
                    st.code(
                        (
                            f"~ [{item['index']}]\n"
                            f"  before: {item['before']}\n"
                            f"  after:  {item['after']}"
                        ),
                        language="yaml",
                    )

st.divider()
st.markdown(
    "Тулза CLI: `python tools/dsl_diff.py before.yaml after.yaml` "
    "(см. `tools/dsl_diff.py --help`)."
)
