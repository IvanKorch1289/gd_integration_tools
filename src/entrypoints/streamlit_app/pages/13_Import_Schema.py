"""Import Schema — загрузка OpenAPI / Postman и генерация Pydantic + DSL routes.

Страница позволяет загрузить spec-файл прямо из UI и посмотреть, какие
модели и роуты будут созданы в ``src/schemas/auto/`` и
``config/routes/imported/``. Полезна для быстрого onboarding-а
внешних API без ручного описания схем.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import streamlit as st

st.set_page_config(page_title="Import Schema", page_icon=":inbox_tray:", layout="wide")
st.header(":inbox_tray: Импорт OpenAPI / Postman → Pydantic")

st.caption(
    "Загрузите OpenAPI (YAML/JSON) или Postman Collection (JSON), и инструмент "
    "сгенерирует Pydantic-модели и скелет DSL-роутов. "
    "Авто-файлы кладутся в src/schemas/auto/ и config/routes/imported/."
)

source_kind = st.radio(
    "Формат источника",
    ["OpenAPI 3.x", "Postman Collection v2.1"],
    horizontal=True,
)

uploaded = st.file_uploader(
    "Файл спецификации",
    type=["yaml", "yml", "json"],
    help="OpenAPI 3.x YAML/JSON или Postman v2.1 JSON",
)

if uploaded and st.button("Сгенерировать"):
    from app.tools.schema_importer import SchemaImporter

    importer = SchemaImporter()
    with tempfile.NamedTemporaryFile(
        mode="wb", suffix=Path(uploaded.name).suffix, delete=False
    ) as tmp:
        tmp.write(uploaded.getvalue())
        tmp_path = Path(tmp.name)

    try:
        if source_kind.startswith("OpenAPI"):
            models_path, routes_path = importer.from_openapi(tmp_path)
        else:
            models_path, routes_path = importer.from_postman(tmp_path)
    except Exception as exc:  # noqa: BLE001
        st.error(f"Ошибка импорта: {exc}")
    else:
        st.success("Готово!")
        col_models, col_routes = st.columns(2)
        with col_models:
            st.subheader("Pydantic-модели")
            st.code(models_path.read_text(encoding="utf-8"), language="python")
            st.caption(f"Путь: `{models_path}`")
        with col_routes:
            st.subheader("DSL YAML-routes")
            st.code(routes_path.read_text(encoding="utf-8"), language="yaml")
            st.caption(f"Путь: `{routes_path}`")
    finally:
        tmp_path.unlink(missing_ok=True)

st.divider()
st.subheader("CLI")
st.code(
    """
uv run manage.py import-schema openapi path/to/spec.yaml
uv run manage.py import-schema postman path/to/collection.json
""".strip(),
    language="bash",
)
