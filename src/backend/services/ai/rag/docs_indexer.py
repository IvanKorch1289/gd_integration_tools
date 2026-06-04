"""DocsIndexer — ingest project markdown docs (CLAUDE.md, .claude/, docs/)
в Qdrant для RAG-powered search.

Sprint 40 W5 (v15 §10): "RAG over project documentation". Async-first,
DI-friendly, graceful degradation (no-qdrant → in-memory fallback).

Использование::

    from src.backend.services.ai.rag.docs_indexer import DocsIndexer

    indexer = DocsIndexer(qdrant_client=qdrant, embedding_model="text-embedding-3-small")
    n = await indexer.index_docs()
    hits = await indexer.search("как поднять dev среду?", limit=5)
"""

from __future__ import annotations

import hashlib
import logging
import re
from pathlib import Path
from typing import Any

__all__ = ("DocsIndexer", "InMemoryQdrantFallback")

logger = logging.getLogger(__name__)

_DEFAULT_ROOTS: tuple[str, ...] = (
    "CLAUDE.md",
    ".claude/CLAUDE.md",
    "docs/users",
    "docs/devs",
)
_EMBED_DIM = 64


def _h(text: str) -> str:
    """sha256[:16] — stable id/hash for content."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def _embed_offline(text: str, dim: int = _EMBED_DIM) -> list[float]:
    """Hash-based embedder (offline/unit). Не ML-grade, но стабильный."""
    vec = [0.0] * dim
    for tok in re.findall(r"\w+", (text or "").lower()):
        vec[int(hashlib.md5(tok.encode()).hexdigest(), 16) % dim] += 1.0  # noqa: S324
    n = sum(v * v for v in vec) ** 0.5
    return [v / n for v in vec] if n > 0 else vec


def _cosine(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = sum(x * x for x in a) ** 0.5
    nb = sum(x * x for x in b) ** 0.5
    return dot / (na * nb) if na and nb else 0.0


class InMemoryQdrantFallback:
    """Минимальный in-memory Qdrant-substitute: get/create/upsert/search."""

    def __init__(self) -> None:
        self._coll: dict[str, dict[str, dict[str, Any]]] = {}
        self._vec: dict[str, dict[str, list[float]]] = {}

    def get_collection(self, name: str) -> dict[str, Any]:
        if name not in self._coll:
            raise ValueError(f"collection {name!r} not found")
        return {"name": name}

    def create_collection(self, name: str, **_kwargs: Any) -> None:
        self._coll.setdefault(name, {})
        self._vec.setdefault(name, {})

    def upsert(self, collection_name: str, points: Any) -> None:
        coll = self._coll.setdefault(collection_name, {})
        vecs = self._vec.setdefault(collection_name, {})
        for p in points:
            pid = str(getattr(p, "id", None) or p["id"])
            payload = getattr(p, "payload", None) or p.get("payload") or {}
            vecs[pid] = list(getattr(p, "vector", None) or p.get("vector") or [])
            coll[pid] = dict(payload)

    def search(  # noqa: ARG002 — query_filter unsupported in fallback
        self,
        collection_name: str,
        query_vector: list[float],
        limit: int = 5,
        query_filter: Any = None,
    ) -> list[Any]:
        vecs = self._vec.get(collection_name, {})
        coll = self._coll.get(collection_name, {})
        if not vecs:
            return []
        scored = [(p, _cosine(query_vector, v)) for p, v in vecs.items()]
        scored.sort(key=lambda x: x[1], reverse=True)

        class _Hit:
            __slots__ = ("id", "payload", "score")

            def __init__(self, pid: str, score: float, payload: dict[str, Any]) -> None:
                self.id, self.score, self.payload = pid, score, payload

        return [_Hit(p, s, coll[p]) for p, s in scored[:limit]]


class DocsIndexer:
    """Ingest project markdown docs → Qdrant → RAG search.

    Per v15 §10 W5: CLAUDE.md, .claude/CLAUDE.md, docs/users/*.md,
    docs/devs/*.md → Qdrant collection ``project_docs`` (default).

    Idempotent: chunk id = sha256(content)[:16] — повторный ingest не
    плодит дубликаты (Qdrant upsert по существующему id → overwrite).
    Graceful: ``qdrant_client is None`` → :class:`InMemoryQdrantFallback`.
    """

    def __init__(
        self,
        *,
        qdrant_client: Any = None,
        embedding_model: str = "text-embedding-3-small",
        collection_name: str = "project_docs",
        chunk_size: int = 512,
        chunk_overlap: int = 50,
    ) -> None:
        self._qdrant = qdrant_client or InMemoryQdrantFallback()
        self._embedding_model = embedding_model
        self._collection_name = collection_name
        self._chunk_size = max(1, chunk_size)
        self._chunk_overlap = min(max(0, chunk_overlap), self._chunk_size - 1)
        self._fallback = qdrant_client is None
        self._embedder: Any = None
        self._collection_ready = False

    @property
    def collection_name(self) -> str:
        return self._collection_name

    @property
    def is_fallback(self) -> bool:
        return self._fallback

    def set_embedder(self, embed_fn: Any) -> None:
        """DI: sync/async ``(texts: list[str]) -> list[list[float]]``."""
        self._embedder = embed_fn

    def _ensure_collection(self) -> None:
        if self._collection_ready:
            return
        try:
            self._qdrant.get_collection(self._collection_name)
        except Exception:  # noqa: BLE001
            try:
                from qdrant_client.models import Distance, VectorParams

                self._qdrant.create_collection(
                    collection_name=self._collection_name,
                    vectors_config=VectorParams(size=384, distance=Distance.COSINE),
                )
            except Exception:  # noqa: BLE001
                self._qdrant.create_collection(self._collection_name)
        self._collection_ready = True

    def discover_docs(self, roots: list[str] | None = None) -> list[Path]:
        """Find all .md files в roots. Default: CLAUDE.md, .claude/, docs/users, docs/devs."""
        candidates = list(roots) if roots is not None else list(_DEFAULT_ROOTS)
        found: set[Path] = set()
        for raw in candidates:
            p = Path(raw)
            if not p.exists():
                continue
            if p.is_file() and p.suffix.lower() == ".md":
                found.add(p.resolve())
            elif p.is_dir():
                found.update(md.resolve() for md in p.rglob("*.md"))
        return sorted(found)

    def chunk_text(self, text: str, metadata: dict[str, Any]) -> list[dict[str, Any]]:
        """Split ``text`` → chunks of ``chunk_size`` chars with ``chunk_overlap``.

        Каждый chunk: ``id`` (sha256[:16]), ``text``, ``metadata`` (file, line,
        hash, source_path, chunk_index). Empty/whitespace text → [].
        """
        if not text or not text.strip():
            return []
        step = max(1, self._chunk_size - self._chunk_overlap)
        chunks: list[dict[str, Any]] = []
        idx, offset = 0, 0
        while offset < len(text):
            piece = text[offset : offset + self._chunk_size]
            if piece.strip():
                chunks.append(
                    {
                        "id": _h(piece),
                        "text": piece,
                        "metadata": {
                            **metadata,
                            "line": text.count("\n", 0, offset) + 1,
                            "chunk_index": idx,
                            "hash": _h(piece),
                        },
                    }
                )
                idx += 1
            offset += step
        return chunks

    async def _embed(self, texts: list[str]) -> list[list[float]]:
        if self._embedder is None:
            return [_embed_offline(t) for t in texts]
        r = self._embedder(texts)
        if hasattr(r, "__await__"):
            r = await r  # type: ignore[func-returns-value]
        return list(r)

    def _build_points(
        self, chunks: list[dict[str, Any]], vecs: list[list[float]]
    ) -> list[Any]:
        """PointStruct → Qdrant, dict fallback → in-memory substitute."""
        try:
            from qdrant_client.models import PointStruct

            return [
                PointStruct(
                    id=chunks[i]["id"],
                    vector=vecs[i],
                    payload={"document": chunks[i]["text"], **chunks[i]["metadata"]},
                )
                for i in range(len(chunks))
            ]
        except Exception:  # noqa: BLE001
            return [
                {
                    "id": chunks[i]["id"],
                    "vector": vecs[i],
                    "payload": {"document": chunks[i]["text"], **chunks[i]["metadata"]},
                }
                for i in range(len(chunks))
            ]

    async def index_docs(self, docs: list[Path] | None = None) -> int:
        """Discover + chunk + embed + upsert. Returns N chunks (idempotent)."""
        paths = docs if docs is not None else self.discover_docs()
        if not paths:
            return 0
        self._ensure_collection()
        all_chunks: list[dict[str, Any]] = []
        for path in paths:
            try:
                raw = path.read_text(encoding="utf-8", errors="ignore")
            except OSError as exc:
                logger.warning("docs_indexer.read_failed path=%s err=%s", path, exc)
                continue
            all_chunks.extend(
                self.chunk_text(
                    raw,
                    metadata={
                        "source_path": str(path),
                        "file": path.name,
                        "file_hash": _h(raw),
                    },
                )
            )
        if not all_chunks:
            return 0
        vecs = await self._embed([c["text"] for c in all_chunks])
        self._qdrant.upsert(
            collection_name=self._collection_name,
            points=self._build_points(all_chunks, vecs),
        )
        return len(all_chunks)

    async def search(self, query: str, *, limit: int = 5) -> list[dict[str, Any]]:
        """RAG search: query → top-N relevant chunks. Empty query → ValueError."""
        if not query or not query.strip():
            raise ValueError("query must be non-empty")
        self._ensure_collection()
        try:
            results = self._qdrant.search(
                collection_name=self._collection_name,
                query_vector=(await self._embed([query]))[0],
                limit=limit,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("docs_indexer.search_failed: %s", exc)
            return []
        out: list[dict[str, Any]] = []
        for r in results:
            pid = getattr(r, "id", None) or (
                r.get("id") if isinstance(r, dict) else None
            )
            raw_score = getattr(r, "score", None) or (
                r.get("score") if isinstance(r, dict) else None
            )
            payload = getattr(r, "payload", None) or (
                r.get("payload") if isinstance(r, dict) else {}
            )
            out.append(
                {
                    "id": str(pid),
                    "score": float(raw_score) if raw_score is not None else 0.0,
                    "document": (payload or {}).get("document", ""),
                    "metadata": {
                        k: v for k, v in (payload or {}).items() if k != "document"
                    },
                }
            )
        return out
