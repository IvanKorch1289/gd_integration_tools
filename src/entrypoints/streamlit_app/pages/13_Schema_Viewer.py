"""Schema Viewer — просмотр API-схем (OpenAPI/AsyncAPI/GraphQL/gRPC).

Страница показывает все схемы, которые публикует приложение, в одном UI.
Ссылки ведут на оригинальные документации (Swagger UI, GraphQL Playground,
proto-viewer), а содержимое встраивается через iframe / code-блок.
"""

from __future__ import annotations

import streamlit as st

st.set_page_config(page_title="Schemas", page_icon=":bookmark_tabs:", layout="wide")
st.header(":bookmark_tabs: API-схемы")

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
    st.markdown("- [GraphiQL playground](/graphql)")
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
    xml_text = st.text_area("XML или XSD контент", height=200, key="schema_xml_text")
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
                    etree.tostring(root, pretty_print=True).decode(),
                    language="xml",
                )
        except Exception as exc:  # noqa: BLE001
            st.error(f"Парсинг XML/XSD не удался: {exc}")
    else:
        st.info("Вставьте XML или XSD контент в поле выше.")
