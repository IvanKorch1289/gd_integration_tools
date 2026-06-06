"""Onboarding Checklist — 7-шаговый старт для нового разработчика (S10 K5 W5)."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import streamlit as st

from src.frontend.streamlit_app.shared.components import setup_page

_root = Path(__file__).resolve().parents[4]

setup_page('Onboarding', ':sparkles:')
st.header("Onboarding Checklist")
st.caption(
    "Sprint 10 K5 W5 — путь от чистого clone до первого route и плагина "
    "за ~1 час. Каждый шаг помечен ✅ когда выполнен (state в session)."
)


STEPS: list[dict] = [
    {
        "title": "1. Склонировать репозиторий",
        "key": "step1_clone",
        "description": (
            "```bash\n"
            "git clone <repo-url> gd_integration_tools && cd gd_integration_tools\n"
            "uv sync --extra dev-light\n"
            "```\n"
            "После этого появится `.venv/` с базовыми зависимостями (быстрый старт)."
        ),
    },
    {
        "title": "2. make doctor — health check окружения",
        "key": "step2_doctor",
        "description": (
            "`make doctor` проверит Python 3.14+, uv, pyproject.toml, "
            "WAF=0, mypy budget, layer violations и опционально TCP-ping "
            "к сервисам. Все ✓ — можно работать."
        ),
    },
    {
        "title": "3. Запустить dev_light backend",
        "key": "step3_dev",
        "description": (
            "```bash\n"
            "APP_ENV=dev_light make run\n"
            "```\n"
            "Backend поднимется на 127.0.0.1:8000 без полного docker-compose "
            "(SQLite + in-memory cache)."
        ),
    },
    {
        "title": "4. Открыть Streamlit dashboard",
        "key": "step4_streamlit",
        "description": (
            "```bash\n"
            "make streamlit\n"
            "```\n"
            "Откроется этот dashboard (`http://localhost:8501/`). 60+ pages: "
            "Routes / Workflows / RAG / AI Chat / DSL Playground / etc."
        ),
    },
    {
        "title": "5. Создать первый route (make scaffold-route)",
        "key": "step5_route",
        "description": (
            "```bash\n"
            "make scaffold-route NAME=hello_world\n"
            "# или интерактивно:\n"
            "python tools/scaffold.py route\n"
            "```\n"
            "Wizard спросит source / sink / AI? / retry? и сгенерирует "
            "`routes/hello_world/{route.toml, *.dsl.yaml}`."
        ),
    },
    {
        "title": "6. Запустить тесты + simulate",
        "key": "step6_test",
        "description": (
            "```bash\n"
            "make test\n"
            "make simulate ROUTE=hello_world\n"
            "```\n"
            "`make simulate` покажет waterfall шагов без реальной сети."
        ),
    },
    {
        "title": "7. Создать первый plugin / extension",
        "key": "step7_plugin",
        "description": (
            "```bash\n"
            "python tools/codegen_plugin.py new --name my_extension\n"
            "make plugin-dev NAME=my_extension\n"
            "```\n"
            "Plugin-dev mode поднимет infra-only compose и hot-reload, "
            "чтобы быстро итерироваться по коду плагина."
        ),
    },
]


for step in STEPS:
    with st.container():
        col1, col2 = st.columns([1, 12])
        with col1:
            done = st.checkbox(
                " ",
                value=st.session_state.get(step["key"], False),
                key=step["key"],
                label_visibility="hidden",
            )
        with col2:
            label = step["title"]
            if done:
                st.markdown(f"~~{label}~~  :white_check_mark:")
            else:
                st.markdown(f"**{label}**")
            with st.expander("Подробнее", expanded=not done):
                st.markdown(step["description"])

st.divider()

completed = sum(1 for s in STEPS if st.session_state.get(s["key"]))
progress = completed / len(STEPS) if STEPS else 0.0
st.progress(progress, text=f"{completed}/{len(STEPS)} шагов завершено")

col_doctor, col_reset = st.columns(2)
with col_doctor:
    if st.button("🩺 Запустить `make doctor` локально"):
        try:
            res = subprocess.run(
                [sys.executable, "tools/checks/doctor.py", "--quick"],
                capture_output=True,
                text=True,
                cwd=_root,
                timeout=120,
            )
            st.code(res.stdout + res.stderr, language="text")
            if res.returncode == 0:
                st.success("Doctor ✓")
            else:
                st.warning(f"Doctor вернул код {res.returncode}")
        except Exception as exc:
            st.error(f"Не удалось выполнить: {exc}")

with col_reset:
    if st.button("Сбросить прогресс"):
        for s in STEPS:
            st.session_state[s["key"]] = False
        st.rerun()
