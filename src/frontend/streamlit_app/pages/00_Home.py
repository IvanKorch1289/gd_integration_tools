"""Главная страница — навигация и mapping старых закладок (Wave 10.1).

После реорганизации страниц по группам ``00/10/20/30/40/50/60`` старые
ссылки могли остаться у пользователей. Эта страница показывает, какие
страницы изменили префикс, и помогает быстро найти новый путь.
"""

from __future__ import annotations

import streamlit as st

st.set_page_config(page_title="Home", layout="wide")

st.title("GD Integration Tools — Home")

st.markdown(
    """
Навигация сгруппирована по префиксам:

* `00_*` — Onboarding: Tutorial, Glossary.
* `10_*` — Operations: Orders, Routes, Logs, Healthcheck, Queue Monitor,
  Processes, Workflows.
* `20_*` — AI: Chat, Feedback, RAG Console.
* `30_*` — DSL: Playground, Visual Editor, Builder, Templates, Debugger.
* `40_*` — Search & Logs: Audit, Search, Notebooks, Realtime Logs.
* `50_*` — Tools: Codegen, Express Bots, API Caller, Import Schema,
  Invocation Console, S3 Browser, Schema Viewer.
* `60_*` — Admin: Wiki, Cache Explorer, Config Viewer, Feature Flags,
  SQL Admin, Services, Jobs.
"""
)

st.divider()

st.header("Старые → новые префиксы")

_REDIRECTS: list[tuple[str, str]] = [
    ("10_Tutorial → 00_Tutorial", "Onboarding"),
    ("11_Glossary → 00_Glossary", "Onboarding"),
    ("1_Orders → 10_Orders", "Operations"),
    ("2_Routes → 11_Routes", "Operations"),
    ("3_Logs → 12_Logs", "Operations"),
    ("22_Healthcheck_Dashboard → 13_Healthcheck_Dashboard", "Operations"),
    ("15_Queue_Monitor → 14_Queue_Monitor", "Operations"),
    ("16_Processes_Dashboard → 15_Processes_Dashboard", "Operations"),
    ("25_Workflows → 16_Workflows", "Operations"),
    ("4_AI_Chat → 20_AI_Chat", "AI"),
    ("27_AI_Feedback → 21_AI_Feedback", "AI"),
    ("8_DSL_Playground → 30_DSL_Playground", "DSL"),
    ("9_DSL_Visual_Editor → 31_DSL_Visual_Editor", "DSL"),
    ("24_DSL_Templates → 33_DSL_Templates", "DSL"),
    ("12_DSL_Debugger → 34_DSL_Debugger", "DSL"),
    ("19_Audit_Log → 40_Audit_Log", "Search"),
    ("29_Search → 41_Search", "Search"),
    ("28_Notebooks → 42_Notebooks", "Search"),
    ("17_Realtime_Logs → 43_Realtime_Logs", "Search"),
    ("30_Codegen_Wizard → 50_Codegen_Wizard", "Tools"),
    ("30_Express_Bots → 51_Express_Bots", "Tools"),
    ("20_API_Caller → 52_API_Caller", "Tools"),
    ("26_Import_Schema → 53_Import_Schema", "Tools"),
    ("31_Invocation_Console → 54_Invocation_Console", "Tools"),
    ("14_S3_Browser → 55_S3_Browser", "Tools"),
    ("13_Schema_Viewer → 56_Schema_Viewer", "Tools"),
    ("18_Cache_Explorer → 61_Cache_Explorer", "Admin"),
    ("21_Config_Viewer → 62_Config_Viewer", "Admin"),
    ("5_Feature_Flags → 63_Feature_Flags", "Admin"),
    ("23_SQL_Admin → 64_SQL_Admin", "Admin"),
    ("6_Services → 65_Services", "Admin"),
    ("7_Jobs → 66_Jobs", "Admin"),
]

for mapping, group in _REDIRECTS:
    st.write(f"- **{group}** — {mapping}")
