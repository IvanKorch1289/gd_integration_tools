"""Примеры @agent_tool-функций example_plugin (Wave 8.5).

Содержит:

* :mod:`analytics_tools` — Polars-агрегация и DuckDB-запросы;
* :mod:`search_tools` — RAG search/augment, AgentMemory recall.

Загрузка в реестр инструментов через
``ToolRegistry.from_plugin_file(<path>.py)``.
"""

from __future__ import annotations
