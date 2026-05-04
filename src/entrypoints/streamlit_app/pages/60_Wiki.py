"""Wiki — full-text поиск по docs/ через Whoosh (Wave 10.2)."""

from __future__ import annotations

import time
from pathlib import Path

import streamlit as st

st.set_page_config(page_title="Wiki", layout="wide")

st.title("Wiki — поиск по документации")

# Lazy-import чтобы set_page_config был первым st-вызовом.
from src.services.wiki.whoosh_index import WhooshIndex


@st.cache_resource(show_spinner=False)
def _get_index() -> WhooshIndex:
    idx = WhooshIndex()
    idx.build(force=False)
    return idx


idx = _get_index()
total = idx.doc_count()
st.caption(f"Документов в индексе: {total}")

col1, col2 = st.columns([4, 1])
query = col1.text_input("Запрос", "")
top = col2.slider("top", 1, 50, 20)

if query:
    t0 = time.perf_counter()
    hits = idx.search(query, top=top)
    dt = (time.perf_counter() - t0) * 1000
    st.caption(f"Найдено: {len(hits)} · {dt:.0f} ms")

    for h in hits:
        path = Path(h.path)
        st.markdown(f"**[{h.title}]({h.path})** · {h.path}  · score={h.score:.2f}")
        if h.snippet:
            st.markdown(h.snippet, unsafe_allow_html=True)
        st.divider()

if st.button("Перестроить индекс"):
    with st.spinner("Reindex…"):
        n = idx.build(force=True)
    st.success(f"Reindex done: {n} docs")
