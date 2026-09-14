"""Data Lineage Graph — pure-Python implementation (Wave 4 #73).

Использует dict-based adjacency list для O(V+E) traversal.
"""

from __future__ import annotations

import enum
import logging
from collections import defaultdict, deque
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)

__all__ = (
    "EdgeKind",
    "LineageEdge",
    "LineageGraph",
    "LineageNode",
    "NodeKind",
    "get_lineage_graph",
)


class NodeKind(str, enum.Enum):
    """Type of node в lineage graph."""

    TABLE = "table"
    ROUTE = "route"
    TRANSFORM = "transform"
    SOURCE = "source"
    SINK = "sink"
    EXTERNAL_SYSTEM = "external_system"
    DATASET = "dataset"


class EdgeKind(str, enum.Enum):
    """Type of edge в lineage graph."""

    READ = "read"
    WRITE = "write"
    TRANSFORM = "transform"
    PUBLISH = "publish"
    SUBSCRIBE = "subscribe"
    DERIVE = "derive"


@dataclass(slots=True)
class LineageNode:
    """Entity в lineage graph.

    Attributes:
        id: Unique node ID (table name, route_id, etc).
        kind: Type of node.
        owner: Team/person responsible.
        description: Human-readable description.
        metadata: Additional attributes.
    """

    id: str
    kind: NodeKind
    owner: str = ""
    description: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(slots=True)
class LineageEdge:
    """Directed edge между двумя nodes.

    Attributes:
        source: Source node ID.
        target: Target node ID.
        kind: Type of edge.
        description: Optional label.
    """

    source: str
    target: str
    kind: EdgeKind
    description: str = ""


class LineageGraph:
    """Directed graph для data lineage traversal."""

    def __init__(self) -> None:
        self._nodes: dict[str, LineageNode] = {}
        # adjacency: source → list[(target, edge_kind)]
        self._forward: dict[str, list[tuple[str, EdgeKind]]] = defaultdict(list)
        # reverse: target → list[(source, edge_kind)]
        self._backward: dict[str, list[tuple[str, EdgeKind]]] = defaultdict(list)

    # ─── CRUD ─────────────────────────────────────────────

    def add_node(self, node: LineageNode) -> None:
        """Register a node."""
        if node.id in self._nodes:
            logger.debug("LineageGraph: overwriting existing node id=%s", node.id)
        self._nodes[node.id] = node

    def add_edge(self, edge: LineageEdge) -> None:
        """Register edge (auto-creates missing nodes)."""
        # Auto-create placeholder nodes if missing.
        if edge.source not in self._nodes:
            self._nodes[edge.source] = LineageNode(
                id=edge.source, kind=NodeKind.EXTERNAL_SYSTEM
            )
        if edge.target not in self._nodes:
            self._nodes[edge.target] = LineageNode(
                id=edge.target, kind=NodeKind.EXTERNAL_SYSTEM
            )
        self._forward[edge.source].append((edge.target, edge.kind))
        self._backward[edge.target].append((edge.source, edge.kind))

    def get_node(self, node_id: str) -> LineageNode | None:
        return self._nodes.get(node_id)

    def list_nodes(self) -> list[LineageNode]:
        return list(self._nodes.values())

    def size(self) -> int:
        return len(self._nodes)

    def edge_count(self) -> int:
        return sum(len(v) for v in self._forward.values())

    def clear(self) -> None:
        self._nodes.clear()
        self._forward.clear()
        self._backward.clear()

    # ─── Traversal ─────────────────────────────────────────

    def upstream(self, node_id: str, *, max_depth: int | None = None) -> dict[str, str]:
        """Find all upstream nodes (sources).

        Returns:
            Dict {node_id: kind.value} of all upstream nodes.
        """
        return self._bfs(self._backward, node_id, max_depth)

    def downstream(
        self, node_id: str, *, max_depth: int | None = None
    ) -> dict[str, str]:
        """Find all downstream nodes (consumers).

        Returns:
            Dict {node_id: kind.value} of all downstream nodes.
        """
        return self._bfs(self._forward, node_id, max_depth)

    def _bfs(
        self,
        adjacency: dict[str, list[tuple[str, EdgeKind]]],
        start: str,
        max_depth: int | None,
    ) -> dict[str, str]:
        """BFS через adjacency.

        Excludes start node from result (semantic: "what feeds into X").

        max_depth semantics:
        - max_depth=0: empty (only start, excluded).
        - max_depth=1: direct neighbors only.
        - max_depth=2: direct + neighbors-of-neighbors.
        """
        if start not in self._nodes:
            return {}
        visited: dict[str, str] = {}
        queue: deque[tuple[str, int]] = deque()
        for neighbor_id, _ in adjacency.get(start, []):
            if neighbor_id not in visited:
                visited[neighbor_id] = self._nodes[neighbor_id].kind.value
                queue.append((neighbor_id, 1))
        while queue:
            node_id, depth = queue.popleft()
            if max_depth is not None and depth >= max_depth:
                continue
            for neighbor_id, _ in adjacency.get(node_id, []):
                if neighbor_id not in visited:
                    visited[neighbor_id] = self._nodes[neighbor_id].kind.value
                    queue.append((neighbor_id, depth + 1))
        return visited

    def impact_of(self, node_id: str) -> dict[str, str]:
        """Alias для downstream() — blast radius analysis."""
        return self.downstream(node_id)

    def lineage_of(self, node_id: str) -> dict[str, str]:
        """Alias для upstream() — sources of data."""
        return self.upstream(node_id)

    def path(self, source: str, target: str) -> list[str] | None:
        """Shortest path source → target через BFS."""
        if source not in self._nodes or target not in self._nodes:
            return None
        if source == target:
            return [source]
        visited: dict[str, str | None] = {source: None}
        queue: deque[str] = deque([source])
        while queue:
            node_id = queue.popleft()
            if node_id == target:
                # Reconstruct path.
                path = [target]
                cur: str = target
                while visited.get(cur) is not None:
                    parent = visited[cur]
                    if parent is None:
                        break
                    cur = parent
                    path.append(cur)
                return list(reversed(path))
            for neighbor_id, _ in self._forward.get(node_id, []):
                if neighbor_id not in visited:
                    visited[neighbor_id] = node_id
                    queue.append(neighbor_id)
        return None

    def detect_cycles(self) -> list[list[str]]:
        """Detect cycles в графе.

        Returns:
            List of cycles (each cycle = list of node IDs).
        """
        WHITE, GRAY, BLACK = 0, 1, 2
        color: dict[str, int] = {n: WHITE for n in self._nodes}
        cycles: list[list[str]] = []
        path: list[str] = []

        def dfs(node_id: str) -> None:
            color[node_id] = GRAY
            path.append(node_id)
            for neighbor_id, _ in self._forward.get(node_id, []):
                if color[neighbor_id] == GRAY:
                    # Cycle found.
                    cycle_start = path.index(neighbor_id)
                    cycles.append(path[cycle_start:] + [neighbor_id])
                elif color[neighbor_id] == WHITE:
                    dfs(neighbor_id)
            path.pop()
            color[node_id] = BLACK

        for node_id in self._nodes:
            if color[node_id] == WHITE:
                dfs(node_id)
        return cycles

    def to_dict(self) -> dict[str, Any]:
        return {
            "nodes": [
                {
                    "id": n.id,
                    "kind": n.kind.value,
                    "owner": n.owner,
                    "description": n.description,
                }
                for n in self._nodes.values()
            ],
            "edges": [
                {"source": s, "target": t, "kind": k.value}
                for s, targets in self._forward.items()
                for t, k in targets
            ],
            "stats": {"node_count": self.size(), "edge_count": self.edge_count()},
        }


_graph: LineageGraph | None = None


def get_lineage_graph() -> LineageGraph:
    global _graph
    if _graph is None:
        _graph = LineageGraph()
    return _graph


def reset_lineage_graph() -> None:
    global _graph
    _graph = None
