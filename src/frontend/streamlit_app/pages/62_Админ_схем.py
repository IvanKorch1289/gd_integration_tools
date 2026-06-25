"""Schema Admin — объединение Import Schema, Реестр схем и Schema Viewer.

Вкладки:
* Import Schema — OpenAPI / Postman / WSDL → ConnectorSpec.
* Реестр схем — просмотр, валидация, diff схем.
* API Schemas — OpenAPI/GraphQL/gRPC/AsyncAPI/SOAP/XML.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import streamlit as st

from src.frontend.streamlit_app.shared.components import setup_page

setup_page("Админ схем", ":card_index_dividers:")
st.header(":card_index_dividers: Админ схем")

tab_import, tab_registry, tab_viewer = st.tabs(
    ["Импорт схемы", "Реестр схем", "API-схемы"]
)

with tab_import:
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
        from src.backend.core.interfaces.import_gateway import (
            ImportSource,
            ImportSourceKind,
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

with tab_registry:
    try:
        from src.backend.core.config.features import feature_flags as _ff

        _FLAG_ENABLED = _ff.frontend_schema_registry_ui
    except Exception:  # noqa: BLE001
        _FLAG_ENABLED = False

    from src.frontend.streamlit_app.services.schema_registry_client import (  # noqa: E402
        diff_schemas,
        list_schemas,
        read_schema,
        validate_openapi,
    )

    with st.sidebar:
        st.subheader("Настройки")
        flag_override = st.toggle(
            "frontend_schema_registry_ui",
            value=_FLAG_ENABLED,
            help=(
                "Feature-flag K5 W1. Production-значение задаётся через "
                "переменную окружения FEATURE_FRONTEND_SCHEMA_REGISTRY_UI."
            ),
            key="reg_flag",
        )

    st.subheader("Реестр схем")
    st.caption(
        "Единый каталог схем проекта: OpenAPI / WSDL / XSD / Protobuf / AsyncAPI / GraphQL SDL. "
        "Download · Validate · Diff."
    )

    if not flag_override:
        st.warning(
            "Страница отключена feature-flag'ом `frontend_schema_registry_ui`. "
            "Включите toggle в боковой панели для просмотра (сессионный override).",
            icon="⚠️",
        )
        st.stop()

    def _render_schema_tab(
        kind: str, lang: str, label: str, validate_fn: bool = False
    ) -> None:
        st.subheader(label)

        available = list_schemas(kind)
        file_options = ["(ввести путь вручную)"] + [str(p) for p in available]

        selected = st.selectbox(
            "Выбрать схему из репозитория:",
            options=file_options,
            key=f"schema_select_{kind}",
        )

        if selected == "(ввести путь вручную)":
            schema_path_str = st.text_input(
                "Путь к файлу схемы:",
                placeholder="docs/reference/schemas/openapi/api.yaml",
                key=f"schema_path_{kind}",
            )
            schema_path = Path(schema_path_str) if schema_path_str else None
        else:
            schema_path = Path(selected)

        content: str = ""
        if schema_path and schema_path.exists():
            try:
                content = read_schema(schema_path)
            except OSError as exc:
                st.error(f"Ошибка чтения файла: {exc}")
        elif schema_path and not schema_path.exists():
            st.warning(f"Файл не найден: `{schema_path}`")

        if content:
            st.code(content, language=lang, line_numbers=True)

            col_dl, col_val, col_diff = st.columns(3)

            with col_dl:
                filename = schema_path.name if schema_path else f"schema.{lang}"
                st.download_button(
                    label="Скачать",
                    data=content.encode("utf-8"),
                    file_name=filename,
                    mime="text/plain",
                    key=f"dl_{kind}",
                )

            with col_val:
                if validate_fn:
                    if st.button("Валидировать", key=f"validate_{kind}"):
                        ok, msg = validate_openapi(content)
                        if ok:
                            st.success(msg)
                        else:
                            st.error(msg)
                else:
                    st.button(
                        "Валидировать",
                        key=f"validate_{kind}",
                        disabled=True,
                        help="Валидация недоступна для данного типа схем.",
                    )

            with col_diff:
                if st.button("Сравнить с", key=f"diff_btn_{kind}"):
                    st.session_state[f"show_diff_{kind}"] = True

            if st.session_state.get(f"show_diff_{kind}"):
                second_content = st.text_area(
                    "Вставьте вторую схему для сравнения:",
                    height=200,
                    key=f"diff_area_{kind}",
                )
                if second_content.strip():
                    result = diff_schemas(content, second_content)
                    if result:
                        st.code(result, language="diff")
                    else:
                        st.success("Схемы идентичны.")
        else:
            st.info("Выберите файл схемы или введите путь вручную.")

    tab_openapi, tab_wsdl, tab_xsd, tab_proto, tab_async, tab_graphql = st.tabs(
        ["OpenAPI", "WSDL", "XSD", "Protobuf", "AsyncAPI", "GraphQL SDL"]
    )

    with tab_openapi:
        _render_schema_tab("openapi", "yaml", "OpenAPI 3.x / Swagger", validate_fn=True)

    with tab_wsdl:
        _render_schema_tab("wsdl", "xml", "WSDL (SOAP)", validate_fn=False)

    with tab_xsd:
        _render_schema_tab("xsd", "xml", "XSD (XML Schema)", validate_fn=False)

    with tab_proto:
        _render_schema_tab(
            "protobuf", "protobuf", "Protobuf (.proto)", validate_fn=False
        )

    with tab_async:
        _render_schema_tab("asyncapi", "yaml", "AsyncAPI 2.x / 3.x", validate_fn=True)

    with tab_graphql:
        _render_schema_tab("graphql", "graphql", "GraphQL SDL", validate_fn=False)

with tab_viewer:
    st.subheader(":bookmark_tabs: API-схемы")
    st.caption(
        "Единый каталог контрактов приложения — OpenAPI для REST, GraphQL-схема, "
        "AsyncAPI для очередей, описание gRPC protobuf."
    )

    tab_rest, tab_gql, tab_grpc, tab_async, tab_soap, tab_xml = st.tabs(
        [
            "REST (OpenAPI)",
            "GraphQL",
            "gRPC (protobuf)",
            "AsyncAPI",
            "SOAP (WSDL)",
            "XML / XSD",
        ]
    )

    with tab_rest:
        st.subheader("OpenAPI 3.1")
        st.markdown(
            "- [Swagger UI](/docs) — интерактивная документация\n"
            "- [ReDoc](/redoc) — альтернативный view\n"
            "- [openapi.json](/openapi.json) — raw JSON-спецификация"
        )
        st.components.v1.iframe("/docs", height=600)

    with tab_gql:
        st.subheader("GraphQL")
        st.markdown("- [GraphiQL playground](/graphql)  # playground на русском оставляем как proper noun")
        st.info(
            "Схема генерируется из strawberry-классов в src/entrypoints/graphql/schema.py"
        )

    with tab_grpc:
        st.subheader("gRPC protobuf")
        st.markdown(
            "- [Proto viewer](/proto) — список .proto файлов и их содержимое\n"
            "- Reflection включён для grpcui/evans"
        )

    with tab_async:
        st.subheader("AsyncAPI")
        st.info(
            "AsyncAPI schema в разработке. Генерация из FastStream-подписчиков "
            "планируется через ``faststream.asyncapi.get_app_schema``."
        )

    with tab_soap:
        st.subheader("SOAP (WSDL)")
        st.caption(
            "Парсер WSDL на zeep — отображает порты, операции и messages. "
            "Полезно при интеграции с legacy-сервисами (1С, банковский шлюз, госуслуги)."
        )
        wsdl_url = st.text_input(
            "WSDL URL или путь к файлу",
            placeholder="https://example.com/service?wsdl",
            key="schema_wsdl_url",
        )
        if wsdl_url:
            try:
                from zeep import Client

                client = Client(wsdl_url)
                services = client.wsdl.services
                st.success(f"WSDL загружен: {len(services)} service(s)")
                for svc_name, svc in services.items():
                    st.markdown(f"### Service `{svc_name}`")
                    for port_name, port in svc.ports.items():
                        st.markdown(f"**Port** `{port_name}` — `{port.binding.name}`")
                        operations = sorted(port.binding._operations.keys())
                        st.write({"operations": operations})
            except Exception as exc:  # noqa: BLE001
                st.error(f"Не удалось загрузить WSDL: {exc}")
        else:
            st.info("Укажите URL/путь к WSDL для просмотра.")

    with tab_xml:
        st.subheader("XML / XSD")
        st.caption(
            "Просмотр XML-документов и XSD-схем. Для XSD выводится список "
            "элементов и типов; для XML — структура дерева."
        )
        xml_text = st.text_area(
            "XML или XSD контент", height=200, key="schema_xml_text"
        )
        if xml_text.strip():
            try:
                from lxml import etree

                parser = etree.XMLParser(resolve_entities=False, no_network=True)
                root = etree.fromstring(xml_text.encode(), parser=parser)
                ns = root.nsmap.get("xs") or root.nsmap.get("xsd")
                is_xsd = root.tag.endswith("schema") and (
                    ns and "XMLSchema" in ns or "XMLSchema" in (root.tag or "")
                )
                if is_xsd:
                    xs = "{http://www.w3.org/2001/XMLSchema}"
                    elements = [e.get("name") for e in root.findall(f"{xs}element")]
                    types = [
                        t.get("name")
                        for t in root.findall(f"{xs}complexType")
                        + root.findall(f"{xs}simpleType")
                    ]
                    st.success(
                        f"XSD: {len(elements)} элемент(ов), {len(types)} тип(ов)"
                    )
                    st.write({"elements": elements, "types": types})
                else:
                    st.success(f"XML root: <{etree.QName(root).localname}>")
                    st.code(
                        etree.tostring(root, pretty_print=True).decode(), language="xml"
                    )
            except Exception as exc:  # noqa: BLE001
                st.error(f"Парсинг XML/XSD не удался: {exc}")
        else:
            st.info("Вставьте XML или XSD контент в поле выше.")
