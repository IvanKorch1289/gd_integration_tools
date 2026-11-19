"""Регресс: capability-граф включает ВЛОЖЕННЫЕ расширения (волна 36, P2-8).

Манифесты capability лежат не только на верхнем уровне ``extensions/``, но и
внутри групп расширений (``extensions/core_entities/<domain>/plugin.toml``).
Прежний обход (``extensions_dir.iterdir()`` + ``child / "plugin.toml"``) их
не видел — в графе capability отсутствовали декларации вложенных плагинов
(core_entities: db.read/db.write, fs.*).
"""

from __future__ import annotations

import pytest


@pytest.mark.unit
class TestCapabilityGraphCoversNestedExtensions:
    """Граф capability строится по всем манифестам расширений."""

    @staticmethod
    def _graph() -> dict:
        import asyncio

        from src.backend.entrypoints.api.v1.endpoints.admin_capabilities import (
            get_capability_graph,
        )

        return asyncio.run(get_capability_graph())

    def test_nested_plugins_present(self) -> None:
        """Вложенные плагины core_entities видны в графе."""
        graph = self._graph()

        plugins = {node["label"] for node in graph["nodes"] if node["kind"] == "plugin"}

        assert "core_entities_orders" in plugins
        assert "core_entities_users" in plugins
        assert "core_entities_files" in plugins
        assert "core_entities_orderkinds" in plugins

    def test_capabilities_of_nested_plugins_present(self) -> None:
        """Capability вложенных плагинов попадают в граф."""
        graph = self._graph()

        capabilities = {
            node["label"] for node in graph["nodes"] if node["kind"] == "capability"
        }

        assert "db.read" in capabilities
        assert "db.write" in capabilities

    def test_graph_is_consistent(self) -> None:
        """Каждое ребро ссылается на существующие узлы."""
        graph = self._graph()

        node_ids = {node["id"] for node in graph["nodes"]}
        for edge in graph["edges"]:
            assert edge["source"] in node_ids
            assert edge["target"] in node_ids
