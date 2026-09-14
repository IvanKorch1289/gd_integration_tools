"""Data Lineage Graph (Wave 4 #73).

Проблема:
    Непонятно, откуда появились данные в БД:
    - Какой route/transform их создал?
    - Какой consumer читает эти данные?
    - Какие поля были изменены?

Решение:
    ``LineageGraph`` — pure-Python граф lineage:

    1. ``LineageNode`` — entity (table, route, transform, sink, source).
    2. ``LineageEdge`` — connection (read, write, transform).
    3. ``LineageGraph`` — register nodes + edges, query traversal.
    4. ``upstream(node)`` / ``downstream(node)`` — graph traversal.
    5. ``impact_of(node)`` — все downstream entities (blast radius).
    6. Pure-Python, in-memory. Production → graph DB (Neo4j/Tigergraph).

Использование::

    from src.backend.core.lineage_graph import (
        LineageNode, LineageEdge, NodeKind, EdgeKind,
        get_lineage_graph,
    )

    graph = get_lineage_graph()
    graph.add_node(LineageNode(id="orders", kind=NodeKind.TABLE))
    graph.add_node(LineageNode(id="order-create", kind=NodeKind.ROUTE))
    graph.add_edge(LineageEdge(
        source="order-create", target="orders", kind=EdgeKind.WRITE
    ))

    # Find blast radius.
    affected = graph.downstream("orders")
    print(affected)  # {'order-create': 'route'}
"""

from __future__ import annotations

from src.backend.core.lineage_graph.graph import (
    EdgeKind,
    LineageEdge,
    LineageGraph,
    LineageNode,
    NodeKind,
    get_lineage_graph,
)

__all__ = (
    "EdgeKind",
    "LineageEdge",
    "LineageGraph",
    "LineageNode",
    "NodeKind",
    "get_lineage_graph",
)
