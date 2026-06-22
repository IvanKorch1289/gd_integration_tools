"""Workflow Templates tab для 33_DSL_Templates (TD-013 PoC regrouping).

Извлечено из ``33_DSL_Templates.py`` (S142 W1). Содержит render-функцию
для workflow templates (S12 K3 W5 + K5 W1): semantic search + per-template
YAML/Mermaid sub-tabs + Deploy-as-new-workflow flow.

**API**:
* :func:`render_workflow_templates` — top-level entry, вызывается из
  :func:`src.frontend.streamlit_app.pages._groups.dsl.dsl_templates.render`
  когда ``st.session_state[PAGE_MODE_KEY] == "Workflow Templates"``.

**Lazy imports**:
* ``streamlit`` — module-level import skipped (модуль import-safe в
  unit-тестах без ``streamlit`` install).
* ``yaml`` (stdlib alias) — локально внутри ``_render_template_card``,
  чтобы не делать module-level stdlib import.
* :func:`httpx` as ``requests`` — внутри Deploy button click handler
  (lazy, чтобы не тянуть httpx при import time).
* :class:`WorkflowDeclaration`, :func:`to_mermaid` — импортируются
  module-level (требуются для type checks и contract'а; cycle-safe).

**Wave**: ``[wave:s142/w1-td013-streamlit-pilot]``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    # TYPE_CHECKING-only for type hints (cycle-safe, no runtime
    # backend import from frontend per layer rules).
    from src.frontend.streamlit_app.api_clients import APIClient


__all__ = ("render_workflow_templates",)


def render_workflow_templates(client: "APIClient") -> None:
    """S12 K3 W5 + K5 W1: workflow templates с Mermaid preview.

    Args:
        client: API client (для Deploy POST). Семантика идентична
            оригинальному ``_render_workflow_templates``.

    Flow:
        1. ``get_template_registry().load_all()`` — S12 K3 W5 registry.
        2. Опционально — semantic search по query (``registry.search_semantic``).
        3. Per template — expander с ``_render_template_card`` (YAML tab +
           Mermaid tab + Deploy input + Deploy button).
    """
    import streamlit as st

    # S44 W2: прямой импорт из services (был try/except с мёртвым
    # ``dsl.workflow.template_registry_compat``, модуль не существует).
    from src.backend.services.workflows.template_registry import (
        get_template_registry,
    )

    registry = get_template_registry()
    all_templates = registry.load_all()

    if not all_templates:
        st.warning(
            "Каталог workflow templates пуст. "
            "Templates ожидаются в src/backend/dsl/workflow/templates/*.yaml."
        )
        return

    query = st.text_input(
        "Search (semantic)", placeholder="incident handling / kyc / data..."
    )

    if query.strip():
        matches = registry.search_semantic(query, top_k=10)
        templates_to_show = [t for t, _ in matches]
    else:
        templates_to_show = all_templates

    st.caption(f"Показано {len(templates_to_show)} из {len(all_templates)}.")

    for tmpl in templates_to_show:
        with st.expander(
            f"📄 {tmpl.name} ({tmpl.step_count} шагов) — {', '.join(tmpl.tags)}"
        ):
            _render_template_card(tmpl, client)


def _render_template_card(tmpl, client: "APIClient") -> None:
    """Per-template expander content: YAML/Mermaid tabs + Deploy flow.

    Args:
        tmpl: WorkflowTemplate dataclass (raw dict + metadata).
        client: API client (для Deploy POST).
    """
    import streamlit as st
    import yaml as _yaml

    st.markdown(tmpl.description)

    yaml_text = _yaml.safe_dump(tmpl.raw, allow_unicode=True, sort_keys=False)

    tabyaml, tab_graph = st.tabs(["YAML", "Mermaid"])
    with tabyaml:
        st.code(yaml_text, language="yaml")
    with tab_graph:
        try:
            # S44 W2: facade import (was lazy direct dsl, layer violation).
            from src.backend.services.dsl_portal import WorkflowDeclaration, to_mermaid

            decl = WorkflowDeclaration.model_validate(tmpl.raw)
            mermaid = to_mermaid(decl)
            st.code(mermaid, language="mermaid")
            st.caption("Скопируйте Mermaid-код в mermaid.live для рендера.")
        except Exception as exc:  # noqa: BLE001
            st.error(f"Mermaid render failed: {exc}")

    target = st.text_input(
        "Target directory",
        value=f"extensions/{tmpl.name}/workflows",
        key=f"target_{tmpl.name}",
    )
    if st.button("Deploy as new workflow", key=f"deploy_{tmpl.name}", type="primary"):
        _deploy_template(tmpl, target, client)


def _deploy_template(tmpl, target: str, client: "APIClient") -> None:
    """POST /api/v1/admin/workflow-templates/{name}/deploy.

    Args:
        tmpl: WorkflowTemplate dataclass.
        target: target directory для deploy.
        client: API client.

    Side effects: streamlit error/success message в текущей колонке.
    """
    import streamlit as st

    try:
        import httpx as requests

        base_url = getattr(client, "base_url", "http://localhost:8000")
        resp = requests.post(
            f"{base_url}/api/v1/admin/workflow-templates/{tmpl.name}/deploy",
            json={"target_dir": target, "overwrite": False},
            timeout=10,
        )
        if resp.status_code == 201:
            st.success(f"Workflow {tmpl.name!r} развёрнут в {target}")
        else:
            st.error(f"HTTP {resp.status_code}: {resp.text}")
    except Exception as exc:  # noqa: BLE001
        st.error(f"Deploy failed: {exc}")
