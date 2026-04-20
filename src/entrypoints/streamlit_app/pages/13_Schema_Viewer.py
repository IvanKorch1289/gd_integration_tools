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

tab_rest, tab_gql, tab_grpc, tab_async = st.tabs(
    ["REST (OpenAPI)", "GraphQL", "gRPC (protobuf)", "AsyncAPI"]
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
