"""DSL Templates — каталог шаблонов маршрутов и workflow.

Sprint 12 K5 W1 — расширение для workflow templates:

* toggle: Route blueprints (legacy) / Workflow templates (S12 K3 W5);
* live YAML preview;
* Mermaid graph rendering (через ``to_mermaid``);
* semantic search вход;
* "Deploy as new workflow" → POST /admin/workflow-templates/{name}/deploy.

Sources:
    * Route blueprints — :mod:`app.dsl.templates_library` (legacy через
      ``GET /api/v1/admin/templates``);
    * Workflow templates — ``src/backend/dsl/workflow/templates/`` через
      :func:`WorkflowTemplateRegistry.load_all`.
"""

from __future__ import annotations

import streamlit as st

from src.frontend.streamlit_app.api_clients import get_api_client  # noqa: E402
from src.frontend.streamlit_app.shared.components import setup_page

setup_page("Templates", ":scroll:")
st.header(":scroll: DSL Templates")

mode = st.radio(
    "Каталог",
    options=["Route Blueprints", "Workflow Templates"],
    horizontal=True,
    key="templates_mode",
)

client = get_api_client()


def _render_route_blueprints() -> None:
    """Legacy route blueprints из /api/v1/admin/templates."""
    try:
        templates = client._request("GET", "/api/v1/admin/templates")
        if not isinstance(templates, list):
            templates = []
    except Exception as exc:  # noqa: BLE001
        templates = []
        st.warning(f"Каталог шаблонов недоступен: {exc}")

    if not templates:
        st.info(
            "Шаблоны берутся из `src/dsl/templates_library.py`. "
            "Backend должен экспонировать `GET /api/v1/admin/templates`."
        )
        return

    for tpl in templates:
        name = tpl.get("name", "—")
        descr = tpl.get("description", "")
        with st.expander(f"{name}"):
            st.caption(descr)
            params = tpl.get("params", {})
            if params:
                st.write("**Параметры:**")
                st.json(params)
            yaml_content = tpl.get("yaml", "")
            if yaml_content:
                st.code(yaml_content, language="yaml")
            if st.button("Инстанциировать", key=f"inst_{name}"):
                try:
                    resp = client._request(
                        "POST", f"/api/v1/admin/templates/{name}/instantiate", json={}
                    )
                    st.success(f"Создан route: {resp}")
                except Exception as exc:  # noqa: BLE001
                    st.error(str(exc))


def _render_workflow_templates() -> None:
    """Sprint 12 K3 W5 + K5 W1 — workflow templates с Mermaid preview."""
    try:
        from src.backend.dsl.workflow.template_registry_compat import (  # noqa: E501
            get_template_registry,
        )
    except ImportError:
        from src.backend.services.workflows.template_registry import (
            get_template_registry,
        )

    try:
        from src.backend.dsl.workflow.spec import WorkflowDeclaration
        from src.backend.dsl.workflow.visualize import to_mermaid
    except ImportError as exc:
        st.error(f"Не удалось импортировать visualize/spec: {exc}")
        return

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
            st.markdown(tmpl.description)

            import yaml as _yaml

            yaml_text = _yaml.safe_dump(tmpl.raw, allow_unicode=True, sort_keys=False)

            tab_yaml, tab_graph = st.tabs(["YAML", "Mermaid"])
            with tab_yaml:
                st.code(yaml_text, language="yaml")
            with tab_graph:
                try:
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
            if st.button(
                "Deploy as new workflow", key=f"deploy_{tmpl.name}", type="primary"
            ):
                try:
                    import httpx as requests

                    base_url = getattr(client, "base_url", "http://localhost:8000")
                    resp = requests.post(
                        f"{base_url}/api/v1/admin/workflow-templates/"
                        f"{tmpl.name}/deploy",
                        json={"target_dir": target, "overwrite": False},
                        timeout=10,
                    )
                    if resp.status_code == 201:
                        st.success(f"Workflow {tmpl.name!r} развёрнут в {target}")
                    else:
                        st.error(f"HTTP {resp.status_code}: {resp.text}")
                except Exception as exc:  # noqa: BLE001
                    st.error(f"Deploy failed: {exc}")


if mode == "Route Blueprints":
    _render_route_blueprints()
else:
    _render_workflow_templates()
