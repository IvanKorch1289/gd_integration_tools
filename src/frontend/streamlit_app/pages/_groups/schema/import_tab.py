"""Import Schema tab — extracted from pages/62_Админ_схем.py (S173).

Загружает OpenAPI / Postman / WSDL через ImportGateway → ConnectorSpec.
"""

from __future__ import annotations

import asyncio

import streamlit as st


def render_import_tab() -> None:
    """Render Import Schema tab content."""
    st.subheader(":inbox_tray: Импорт OpenAPI / Postman / WSDL → ConnectorSpec")
    st.caption(
        "Загрузите OpenAPI 3.x (YAML/JSON), Postman Collection v2.1 (JSON) или "
        "WSDL (XML) — W24 ImportGateway распарсит и сохранит ConnectorSpec в "
        "MongoDB-коллекцию ``connector_configs``."
    )

    source_kind = st.radio(
        "Формат источника",
        ["OpenAPI 3.x", "Postman Collection v2.1", "WSDL"],
        horizontal=True,
        key="imp_kind",
    )
    prefix = st.text_input("Префикс для operation_id", value="ext", key="imp_prefix")
    dry_run = st.checkbox(
        "Пробный прогон (не регистрировать actions)", value=False, key="imp_dry"
    )

    uploaded = st.file_uploader(
        "Файл спецификации",
        type=["yaml", "yml", "json", "wsdl", "xml"],
        help="OpenAPI YAML/JSON, Postman v2.1 JSON или WSDL XML",
        key="imp_upload",
    )

    def _kind_value(label: str) -> str:
        if label.startswith("OpenAPI"):
            return "openapi"
        if label.startswith("Postman"):
            return "postman"
        return "wsdl"

    if uploaded and st.button("Импортировать", key="imp_btn"):
        from src.backend.core.frontend_facade import (  # noqa: E402, F401
            get_default_import_service,
            get_import_service,
        )
        from src.backend.core.frontend_facade import (  # noqa: E402, F401
            get_default_import_service,
            get_import_service,
        )

        # S6 fix: facade import через dsl_portal (R3.10d / S36).
        from src.backend.services.dsl_portal import get_import_service

        content = uploaded.getvalue()
        source = ImportSource(
            kind=ImportSourceKind(_kind_value(source_kind)),
            content=content,
            prefix=prefix,
        )
        try:
            result = asyncio.run(
                get_import_service().import_and_register(
                    source, register_actions=not dry_run
                )
            )
        except Exception as exc:  # noqa: BLE001
            st.error(f"Ошибка импорта: {exc}")
        else:
            st.success(f"Готово: {result['status']} (connector={result['connector']})")
            st.json(result)
            secret_refs = result.get("secret_refs_required") or []
            if secret_refs:
                st.warning(
                    "Spec содержит auth-секреты. Загрузите значения в SecretsBackend "
                    "для следующих ключей:"
                )
                st.table(secret_refs)

    st.divider()
    st.subheader("CLI / DSL")
    st.code(
        """
# REST endpoint:
curl -F file=@spec.yaml -F prefix=ext http://localhost:8000/api/v1/imports/openapi

# DSL action:
- action: connector.import
  payload:
    kind: openapi
    content: '<raw>'
    prefix: ext
""".strip(),
        language="bash",
    )
