# Tutorial 06 — Streamlit custom dashboard

> **Prerequisites:** Tutorial 02 (first plugin). ~25 минут.

## Цель

Создать кастомную Streamlit-страницу для plugin, с использованием
`api_client` и `st.fragment` для real-time refresh.

## Шаги

### 1. Создать pages/<NN>_<name>.py в плагине

```python
# extensions/my_plugin/frontend/pages/80_My_Dashboard.py
from __future__ import annotations

import sys
from pathlib import Path

import streamlit as st

_root = Path(__file__).resolve().parents[5]
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

from src.frontend.streamlit_app.api_client import get_api_client

st.set_page_config(page_title="My Dashboard", layout="wide")
st.header(":bar_chart: My Custom Dashboard")

client = get_api_client()


@st.fragment(run_every=10)
def render_metrics() -> None:
    try:
        resp = client.get("/admin/my-plugin/metrics")
        resp.raise_for_status()
        data = resp.json()
    except Exception as exc:  # noqa: BLE001
        st.error(f"Failed: {exc}")
        return

    col1, col2, col3 = st.columns(3)
    col1.metric("Requests", data["requests"])
    col2.metric("Errors", data["errors"])
    col3.metric("p95 latency, ms", data["p95"])


render_metrics()
```

### 2. Зарегистрировать в Streamlit symlink

```bash
ln -s ../extensions/my_plugin/frontend/pages/80_My_Dashboard.py \
      src/frontend/streamlit_app/pages/80_My_Dashboard.py
```

### 3. Проверить отсутствие коллизий

```bash
python tools/checks/streamlit_pages.py
# OK: 56 pages, 0 collisions
```

### 4. Запустить Streamlit

```bash
make streamlit
```

Открыть `http://localhost:8501` → в sidebar появится "My Dashboard".

## What's next?

* Tutorial 07 — RAG pipeline + Streamlit UI.
* Tutorial 10 — Token budget per tenant с budget overview UI.
* `tools/checks/streamlit_pages.py` — pre-prod-check #20 (DoD-10).
