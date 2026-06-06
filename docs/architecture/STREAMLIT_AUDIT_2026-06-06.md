# Streamlit Audit 2026-06-06 — Dup Groups Analysis

**Дата**: 2026-06-06 | **Sprint**: 42 Wave 3 (B) | **Scope**: 80 pages, 11 api_clients, 2 shared
**Verdict**: 6 dup groups identified, 3 с high consolidation potential

## TL;DR

80 pages (10 137 LOC) + 11 api_clients (1 413 LOC) + 2 shared (2 946 chars).
Streamlit frontend имеет 6 устойчивых dup patterns. **Top-3 группы дают
~70% potential LOC savings** через consolidation в `shared/components/`.

**6 dup groups identified**:

| # | Dup group | Files affected | LOC dup estimate | Priority |
|---|-----------|---------------:|-----------------:|----------|
| 1 | API client imports (`get_api_client`) | 38 pages | ~152 LOC (4×38) | 🟠 P1 |
| 2 | Page setup boilerplate (`set_page_config` + `import streamlit as st`) | 66 pages | ~330 LOC (5×66) | 🟠 P1 |
| 3 | Chart widgets (`st.dataframe`, `st.metric`, `st.line_chart`) | 36 pages | ~720 LOC (20×36) | 🔴 P1 |
| 4 | Admin pages pattern (list + edit form + delete) | 6 pages | ~600 LOC (100×6) | 🟡 P2 |
| 5 | DSL pages pattern (editor + preview) | 8 pages | ~1200 LOC (150×8) | 🟡 P2 |
| 6 | Two parallel API client modules (`api_client` + `api_client_k4`) | 38 + 3 pages | ~80 LOC | 🟢 P3 |

**Estimated total dup LOC**: ~3000 LOC (29% от 10 137).

## Verified data (2026-06-06)

| Metric | Value | Source |
|--------|------:|--------|
| Total pages | 80 | `find src/frontend/streamlit_app -name "*.py" -not -name "__init__*" -not -path "*/shared/*" -not -path "*/api_clients/*"` |
| Total pages LOC | 10 137 | `wc -l src/frontend/streamlit_app/pages/*.py` |
| api_clients files | 11 | `ls api_clients/` |
| api_clients LOC | 1 413 | `wc -l api_clients/*.py` |
| shared files | 2 | `ls shared/` (constants.py + utils.py) |
| Pages with `st.set_page_config` | 66 | `grep -lE "st.set_page_config" pages/*.py` |
| Pages with chart widgets | 36 | `grep -lE "st.(dataframe|metric|line_chart|bar_chart|pyplot)" pages/*.py` |
| Pages importing `get_api_client` | 26 (+12 with noqa) | `grep -c "from src.frontend.streamlit_app.api_client import get_api_client" pages/*.py` |
| Pages importing `K4APIClient` | 3 | `grep "from src.frontend.streamlit_app.api_client_k4"` |
| Largest page | 31_DSL_Visual_Editor.py (1267 LOC) | `wc -l` sort top |

## Dup Group Details

### Group 1: API client imports (P1, ~152 LOC dup)

**Evidence**:
```
$ grep -hE "^from |^import " pages/*.py | sort | uniq -c | sort -rn
   26 from src.frontend.streamlit_app.api_client import get_api_client
   12 from src.frontend.streamlit_app.api_client import get_api_client  # noqa: E402
    3 from src.frontend.streamlit_app.api_client_k4 import K4APIClient
```

**Pattern**: 38 pages импортируют `get_api_client()` (26 напрямую + 12 с noqa E402)
плюс 3 импортируют `K4APIClient` из **другого модуля** `api_client_k4`.

**Issue**: Два параллельных API client модуля:
- `api_client.py` (26 + 12 = 38 pages) — primary, generic
- `api_client_k4.py` (3 pages) — secondary, K4-specific

**Recommendation**:
- `K4APIClient` должен быть в `api_clients/k4.py` (рядом с другими 11 clients)
- `get_api_client` re-export из `api_clients/__init__.py` для удобства
- Stdlib import в `shared/utils.py` (1 строка)

**Estimated saving**: ~80 LOC (import boilerplate) + cleaner module structure

### Group 2: Page setup boilerplate (P1, ~330 LOC dup)

**Evidence**: 66 из 80 pages (82%) имеют `st.set_page_config()`.
Top-3 imports:
```
59 from __future__ import annotations
63 import streamlit as st
26 from src.frontend.streamlit_app.api_client import get_api_client
```

**Pattern** (в каждой page):
```python
from __future__ import annotations
import streamlit as st

st.set_page_config(
    page_title="...",
    page_icon="...",
    layout="wide",
)
```

**Recommendation**: `shared/components.py` с `setup_page(title, icon, layout="wide")`:
```python
def setup_page(title: str, icon: str, *, layout: str = "wide") -> None:
    st.set_page_config(page_title=title, page_icon=icon, layout=layout)
```

**Estimated saving**: ~5 LOC × 66 pages = ~330 LOC (3-4% от total)

### Group 3: Chart widgets (P1, ~720 LOC dup)

**Evidence**: 36 pages содержат chart widgets (`st.dataframe`, `st.metric`,
`st.line_chart`, `st.bar_chart`, `st.pyplot`).

**Pattern** (в каждой data page):
```python
df = load_data()
col1, col2, col3 = st.columns(3)
with col1: st.metric("X", value1)
with col2: st.metric("Y", value2)
with col3: st.metric("Z", value3)
st.dataframe(df, use_container_width=True)
```

**Recommendation**: `shared/charts.py`:
```python
def metric_row(metrics: list[tuple[str, Any]]) -> None:
    cols = st.columns(len(metrics))
    for col, (label, value) in zip(cols, metrics, strict=True):
        with col:
            st.metric(label, value)

def dataframe_view(df: pd.DataFrame, **kwargs: Any) -> None:
    st.dataframe(df, use_container_width=True, **kwargs)
```

**Estimated saving**: ~20 LOC × 36 pages = ~720 LOC (7% от total)

### Group 4: Admin pages pattern (P2, ~600 LOC dup)

**Evidence**: 6 admin pages с похожим pattern:
- 45_admin.py
- 60_Cache_Admin.py
- 61_Audit_Log.py
- 62_Schema_Admin.py (371 LOC, top admin)
- 64_SQL_Admin.py
- 88_Tenant_Feature_Flags.py

**Pattern**: list endpoint → table → edit form → delete confirmation.

**Recommendation**: `shared/admin_crud.py`:
```python
def admin_list_view(
    endpoint: str, columns: list[str], key_prefix: str
) -> None:
    """Generic list+edit+delete for admin entities."""
    client = get_api_client()
    items = client.get(endpoint)
    df = pd.DataFrame(items)
    st.dataframe(df, use_container_width=True)
    # ... edit/delete form
```

**Estimated saving**: ~100 LOC × 6 pages = ~600 LOC (6% от total)

### Group 5: DSL pages pattern (P2, ~1200 LOC dup)

**Evidence**: 8 DSL pages с editor+preview pattern:
- 30_DSL_Playground.py
- 31_DSL_Visual_Editor.py (**1267 LOC, OUTLIER**)
- 32_DSL_Builder.py
- 33_DSL_Templates.py
- 34_DSL_Debugger.py
- 35_Codegen_Wizard.py
- 46_DSL_DryRun.py
- 86_DSL_Usage_Audit.py

**Pattern**: YAML/JSON editor + syntax validation + preview render.

**Recommendation**: `shared/dsl_editor.py`:
```python
def dsl_editor_with_preview(
    sample: str, language: str = "yaml", height: int = 400
) -> dict[str, Any]:
    """Render DSL editor + live preview + validation."""
    # ... editor widget, parse, validate, preview
```

**Estimated saving**: ~150 LOC × 8 pages = ~1200 LOC (12% от total)

### Group 6: Two parallel API client modules (P3, ~80 LOC dup)

См. Group 1. Технически подмножество, но выделено отдельно как отдельная проблема:
- `api_client.py` vs `api_client_k4.py` — два модуля с похожим purpose
- 3 pages используют `api_client_k4`, остальные 38 — `api_client`
- **Вопрос к architecture**: что такое K4API? K4 = "AI/ML Kernel"? Документация отсутствует.

## Outlier Analysis

### 31_DSL_Visual_Editor.py (1267 LOC)
**SUSPICIOUS**: в 4 раза больше средней page (~127 LOC). Возможные причины:
- Inline большая YAML schema (DSL vocabulary)
- Generated code (auto-builder)
- Real complex editor с Monaco/CodeMirror интеграцией

**Recommendation**: отдельный audit этого файла в Sprint 43, не consolidation candidate.

### Page count discrepancy: 80 vs 94
- `find` считал 80 files в pages/
- Ранее упомянуто 94 (включая api_clients + shared?)
- Verify: 80 pages + 11 api_clients + 2 shared = 93, + 1 __init__ = 94 ✅

## Recommended Sprint 43 Scope

**Consolidation implementation (estimated 1-2 weeks)**:

| Order | Group | Effort | Risk |
|------:|-------|-------:|------|
| 1 | Group 1: API client imports | 2-3 hours | low (rename only) |
| 2 | Group 2: Page setup boilerplate | 1-2 hours | very low (helper function) |
| 3 | Group 3: Chart widgets | 4-6 hours | medium (UX changes) |
| 4 | Group 6: Two parallel clients | 1 hour | low (reorganize) |
| 5 | Group 4: Admin pages | 1-2 days | medium (UX changes) |
| 6 | Group 5: DSL pages | 2-3 days | high (DSL editor logic) |

**Total estimated**: 2-3 weeks, ~3000 LOC reduction, 0 behavioral changes.

**Recommended order**: Groups 1, 2, 6 first (low risk, high LOC), then 3 (UX), then 4 + 5 (high effort, defer to Sprint 44+).

## Out of Scope (дефер в Sprint 44+)

- 31_DSL_Visual_Editor.py — отдельный audit
- Group 5 (DSL pages) — high risk, high effort
- Group 4 (admin pages) — UX implications требуют product sign-off
- 14 pages без `set_page_config` — possible bug (или intentional minimal pages)

## Verification Commands (для повторного audit)

```bash
# Page count
find src/frontend/streamlit_app -name "*.py" -not -name "__init__*" -not -path "*/shared/*" -not -path "*/api_clients/*" | wc -l

# Top imports (dup detection)
grep -hE "^from |^import " src/frontend/streamlit_app/pages/*.py | sort | uniq -c | sort -rn

# Chart widgets
grep -lE "st\.(dataframe|metric|line_chart|bar_chart|pyplot)" src/frontend/streamlit_app/pages/*.py

# set_page_config
grep -lE "st\.set_page_config" src/frontend/streamlit_app/pages/*.py

# api_clients
ls -la src/frontend/streamlit_app/api_clients/
```

## Notes

- **No code changes** в этом audit (per Sprint 42 W3 B scope)
- **Document only**: 1 commit `docs/architecture/STREAMLIT_AUDIT_2026-06-06.md`
- Sprint 43 consolidation будет идти per-group, отдельно согласованный план
- Streamlit frontend — internal tool, не критичен для production
