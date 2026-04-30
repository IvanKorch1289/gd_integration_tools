"""Import Schema — W24 ImportGateway: OpenAPI / Postman / WSDL → ConnectorSpec.

Загружает спецификацию через async ``ImportService``, показывает результат
импорта (connector_name, version, endpoints, secret_refs) и предоставляет
просмотр сохранённой записи из ``connector_configs``.

Замещает legacy ``SchemaImporter`` (Pydantic codegen + YAML routes на диск).
"""

from __future__ import annotations

import asyncio

import streamlit as st

st.set_page_config(page_title="Import Schema", page_icon=":inbox_tray:", layout="wide")
st.header(":inbox_tray: Импорт OpenAPI / Postman / WSDL → ConnectorSpec")

st.caption(
    "Загрузите OpenAPI 3.x (YAML/JSON), Postman Collection v2.1 (JSON) или "
    "WSDL (XML) — W24 ImportGateway распарсит и сохранит ConnectorSpec в "
    "MongoDB-коллекцию ``connector_configs``."
)

source_kind = st.radio(
    "Формат источника",
    ["OpenAPI 3.x", "Postman Collection v2.1", "WSDL"],
    horizontal=True,
)
prefix = st.text_input("Префикс для operation_id", value="ext")
dry_run = st.checkbox("Dry-run (не регистрировать actions)", value=False)

uploaded = st.file_uploader(
    "Файл спецификации",
    type=["yaml", "yml", "json", "wsdl", "xml"],
    help="OpenAPI YAML/JSON, Postman v2.1 JSON или WSDL XML",
)


def _kind_value(label: str) -> str:
    if label.startswith("OpenAPI"):
        return "openapi"
    if label.startswith("Postman"):
        return "postman"
    return "wsdl"


if uploaded and st.button("Импортировать"):
    from src.core.interfaces.import_gateway import ImportSource, ImportSourceKind
    from src.services.integrations import get_import_service

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
