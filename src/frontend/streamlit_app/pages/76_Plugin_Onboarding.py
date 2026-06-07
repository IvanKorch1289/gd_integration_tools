"""Sprint 14 K5 W6 — Plugin Onboarding Wizard.

4-шаговый wizard для создания нового V11 плагина:

1. **Базовая информация**: name, description, version, requires_core;
2. **Capabilities**: выбор capabilities из vocabulary;
3. **Features**: feature-каркасы (REST endpoint / processor /
   workflow / repository);
4. **Review & Scaffold**: dry-run → подтверждение → backend
   ``POST /api/v1/admin/plugins/scaffold`` создаёт каркас в
   ``extensions/<name>/`` через ``tools.codegen_plugin.scaffold_plugin``.

Feature_flag: ``plugin_onboarding_wizard_enabled`` (default-OFF).
"""

from __future__ import annotations

import streamlit as st

from src.frontend.streamlit_app.api_clients import get_api_client  # noqa: E402
from src.frontend.streamlit_app.shared.components import setup_page

setup_page("Plugin Onboarding", "🧪")
st.title("🧪 Plugin Onboarding Wizard")
st.caption("Sprint 14 K5 W6 — пошаговый scaffold V11 плагина.")

client = get_api_client()


# ── Состояние wizard ────────────────────────────────────────────

if "onboarding_step" not in st.session_state:
    st.session_state["onboarding_step"] = 1
    st.session_state["onboarding_data"] = {
        "name": "",
        "description": "",
        "capabilities": [],
        "features": [],
    }


def _goto(step: int) -> None:
    st.session_state["onboarding_step"] = step


step = st.session_state["onboarding_step"]
data = st.session_state["onboarding_data"]

progress_cols = st.columns(4)
labels = ["1. Info", "2. Capabilities", "3. Features", "4. Review"]
for i, label in enumerate(labels, start=1):
    with progress_cols[i - 1]:
        if i == step:
            st.markdown(f"**▶ {label}**")
        elif i < step:
            st.markdown(f"✅ {label}")
        else:
            st.markdown(f"○ {label}")

st.divider()


# ── Step 1: Info ────────────────────────────────────────────────

if step == 1:
    st.subheader("Базовая информация")
    data["name"] = st.text_input(
        "Имя плагина (snake_case)", value=data["name"], placeholder="credit_pipeline"
    )
    data["description"] = st.text_area(
        "Описание",
        value=data["description"],
        placeholder="Бизнес-задача плагина в одном-двух предложениях.",
    )
    next_disabled = not data["name"]
    if st.button("Далее →", type="primary", disabled=next_disabled):
        _goto(2)
        st.rerun()


# ── Step 2: Capabilities ────────────────────────────────────────

elif step == 2:
    st.subheader("Capabilities (ADR-044)")
    catalog = client.get_capability_catalog()
    vocab = catalog.get("vocabulary", [])
    options = [c["name"] for c in vocab] or [
        "db.read",
        "db.write",
        "secrets.read",
        "net.outbound",
        "code.execute",
        "fs.read",
        "fs.create_new",
        "ai.llm.openai",
    ]
    data["capabilities"] = st.multiselect(
        "Какие ресурсы плагин будет использовать?",
        options=sorted(set(options)),
        default=data["capabilities"],
    )
    cols = st.columns(2)
    if cols[0].button("← Назад"):
        _goto(1)
        st.rerun()
    if cols[1].button("Далее →", type="primary"):
        _goto(3)
        st.rerun()


# ── Step 3: Features ────────────────────────────────────────────

elif step == 3:
    st.subheader("Каркасы фич")
    feature_options = [
        "rest_endpoint",
        "service",
        "processor",
        "workflow",
        "repository",
        "frontend_page",
    ]
    data["features"] = st.multiselect(
        "Какие шаблоны сгенерировать сразу?",
        options=feature_options,
        default=data["features"],
    )
    cols = st.columns(2)
    if cols[0].button("← Назад"):
        _goto(2)
        st.rerun()
    if cols[1].button("Далее →", type="primary"):
        _goto(4)
        st.rerun()


# ── Step 4: Review & Scaffold ───────────────────────────────────

elif step == 4:
    st.subheader("Подтверждение")
    st.json(data)

    cols = st.columns(3)
    if cols[0].button("← Назад"):
        _goto(3)
        st.rerun()

    if cols[1].button("Dry-run preview"):
        preview = client.scaffold_plugin(
            data["name"],
            description=data["description"],
            capabilities=data["capabilities"],
            features=data["features"],
            dry_run=True,
        )
        st.write("**Preview:**")
        st.json(preview)

    if cols[2].button("Создать плагин", type="primary"):
        result = client.scaffold_plugin(
            data["name"],
            description=data["description"],
            capabilities=data["capabilities"],
            features=data["features"],
            dry_run=False,
        )
        if result.get("created"):
            st.success(f"Плагин создан: `{result.get('path')}`")
        else:
            st.error(f"Не удалось создать: {result}")
