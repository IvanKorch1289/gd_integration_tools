"""Schema Registry UI — просмотр, валидация и diff схем (6 типов).

Страница предоставляет единый интерфейс для работы с контрактными схемами
проекта: OpenAPI, WSDL, XSD, Protobuf, AsyncAPI, GraphQL SDL.

Для каждого типа доступны:
- выбор файла схемы из ``docs/reference/schemas/<kind>/`` или ввод пути/URL;
- просмотр содержимого с подсветкой;
- кнопка Validate — sanity-проверка структуры;
- кнопка Download — сохранение файла через браузер;
- кнопка Diff vs — загрузка второй схемы и отображение unified-diff.

Страница активна только при feature_flag ``frontend_schema_registry_ui = True``.
При выключенном флаге отображается информационный баннер.

Зависимости:
    - streamlit (обязательно)
    - jsonschema (опционально, для расширенной валидации)
    - lxml (опционально, для XSD/WSDL)
    - yaml (pyyaml, для YAML-схем)
"""

from __future__ import annotations

from pathlib import Path

import streamlit as st

# Добавляем корень проекта в sys.path для импорта backend-модулей

# ─── Проверка feature-flag ─────────────────────────────────────────────────

try:
    from src.backend.core.config.features import feature_flags as _ff

    _FLAG_ENABLED = _ff.frontend_schema_registry_ui
except Exception:  # noqa: BLE001 — graceful degradation при отсутствии backend
    _FLAG_ENABLED = False

# ─── Импорт хелперов ──────────────────────────────────────────────────────

from src.frontend.streamlit_app.services.schema_registry_client import (  # noqa: E402
    diff_schemas,
    list_schemas,
    read_schema,
    validate_openapi,
)

# ─── Конфигурация страницы ────────────────────────────────────────────────

st.set_page_config(
    page_title="Schema Registry", page_icon=":card_index_dividers:", layout="wide"
)

# ─── Sidebar: feature-flag toggle ─────────────────────────────────────────

with st.sidebar:
    st.subheader("Настройки")
    flag_override = st.toggle(
        "frontend_schema_registry_ui",
        value=_FLAG_ENABLED,
        help=(
            "Feature-flag K5 W1. Production-значение задаётся через "
            "переменную окружения FEATURE_FRONTEND_SCHEMA_REGISTRY_UI."
        ),
    )

# ─── Заголовок ────────────────────────────────────────────────────────────

st.header(":card_index_dividers: Schema Registry")
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

# ─── Вспомогательные функции рендеринга ──────────────────────────────────


def _render_schema_tab(
    kind: str, lang: str, label: str, validate_fn: bool = False
) -> None:
    """Отрисовать содержимое одного tab для конкретного типа схемы.

    Args:
        kind: Идентификатор типа схемы (``openapi``, ``wsdl`` и т.д.).
        lang: Язык для подсветки в st.code (``yaml``, ``xml``, ``graphql``).
        label: Человекочитаемое название для UI-элементов.
        validate_fn: Включить ли кнопку Validate (применима к JSON/YAML схемам).
    """
    st.subheader(label)

    # Список доступных файлов из docs/reference/schemas/
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

        # ── Download ──────────────────────────────────────────────────────
        with col_dl:
            filename = schema_path.name if schema_path else f"schema.{lang}"
            st.download_button(
                label="Download",
                data=content.encode("utf-8"),
                file_name=filename,
                mime="text/plain",
                key=f"dl_{kind}",
            )

        # ── Validate ──────────────────────────────────────────────────────
        with col_val:
            if validate_fn:
                if st.button("Validate", key=f"validate_{kind}"):
                    ok, msg = validate_openapi(content)
                    if ok:
                        st.success(msg)
                    else:
                        st.error(msg)
            else:
                st.button(
                    "Validate",
                    key=f"validate_{kind}",
                    disabled=True,
                    help="Валидация недоступна для данного типа схем.",
                )

        # ── Diff ─────────────────────────────────────────────────────────
        with col_diff:
            if st.button("Diff vs", key=f"diff_btn_{kind}"):
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


# ─── Tabs ─────────────────────────────────────────────────────────────────

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
    _render_schema_tab("protobuf", "protobuf", "Protobuf (.proto)", validate_fn=False)

with tab_async:
    _render_schema_tab("asyncapi", "yaml", "AsyncAPI 2.x / 3.x", validate_fn=True)

with tab_graphql:
    _render_schema_tab("graphql", "graphql", "GraphQL SDL", validate_fn=False)
