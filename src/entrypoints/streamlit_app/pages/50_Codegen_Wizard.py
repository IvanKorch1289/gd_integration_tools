"""Wave 5.6 — Streamlit-wizard для запуска codegen-tools из UI.

Три раздела (tabs):

1. **New Service** — форма для ``codegen_service.py``: name/domain/crud/fields.
2. **Import Swagger** — загрузка swagger.json + connector_name.
3. **Extract** — выбор service-файла → YAML round-trip.

Кнопки выполняют CLI через ``subprocess`` и показывают вывод в expander.
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

import streamlit as st

st.set_page_config(page_title="Codegen Wizard", layout="wide")

ROOT = Path(__file__).resolve().parents[4]


def _run(args: list[str]) -> tuple[int, str, str]:
    """Запускает CLI как subprocess, возвращает (rc, stdout, stderr)."""
    python = shutil.which("python") or sys.executable
    result = subprocess.run(  # noqa: S603 — args полностью контролируются формой
        [python, *args],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        check=False,
    )
    return result.returncode, result.stdout, result.stderr


st.header("Codegen Wizard (Wave 5.6)")

tab_service, tab_swagger, tab_extract = st.tabs(
    ["New Service", "Import Swagger", "Extract YAML"]
)

with tab_service:
    st.subheader("Создать новый сервис")
    name = st.text_input("name (snake_case, мн.ч.)", value="customers")
    domain = st.selectbox("domain", ["core", "ai", "integrations", "ops"])
    crud = st.checkbox("CRUD методы", value=True)
    fields_json = st.text_area(
        "fields JSON",
        value='{"name": "str", "email": "str"}',
        help='Словарь поле:py_type для Create/Update схем',
    )
    if st.button("Сгенерировать"):
        try:
            json.loads(fields_json)
            cmd = [
                "tools/codegen_service.py",
                "--name", name,
                "--domain", domain,
                "--fields", fields_json,
            ]
            if crud:
                cmd.append("--crud")
            rc, out, err = _run(cmd)
            with st.expander("Output", expanded=True):
                st.code(out)
                if err:
                    st.code(err)
            if rc == 0:
                st.success(f"Создан сервис {name} в {domain}")
            else:
                st.error(f"codegen failed (rc={rc})")
        except json.JSONDecodeError as exc:
            st.error(f"fields JSON невалиден: {exc}")

with tab_swagger:
    st.subheader("Импорт Swagger/OpenAPI")
    uploaded = st.file_uploader("swagger.json или .yaml", type=["json", "yaml", "yml"])
    connector = st.text_input("connector name", value="petstore")
    write_module = st.checkbox("Записать сгенерированный модуль", value=False)
    if st.button("Импортировать") and uploaded is not None:
        tmp_path = Path(tempfile.gettempdir()) / uploaded.name
        tmp_path.write_bytes(uploaded.read())
        cmd = [
            "tools/import_swagger.py",
            "--url", str(tmp_path),
            "--connector", connector,
        ]
        if write_module:
            cmd.append("--write")
        rc, out, err = _run(cmd)
        with st.expander("Output", expanded=True):
            st.code(out)
            if err:
                st.code(err)
        if rc == 0:
            st.success(f"Импортирован {connector}")

with tab_extract:
    st.subheader("Extract: Service → YAML")
    service_path = st.text_input(
        "Путь к service-файлу", value="src/services/core/admin.py"
    )
    if st.button("Extract"):
        cmd = ["tools/codegen_extract.py", "--service", service_path]
        rc, out, err = _run(cmd)
        with st.expander("YAML output", expanded=True):
            st.code(out, language="yaml")
            if err:
                st.code(err)
