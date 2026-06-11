"""DocsIndexer — ingest project markdown docs в Qdrant для RAG search.

Sprint 40 W5 (v15 §10): CLAUDE.md, .claude/CLAUDE.md, docs/users/*.md,
docs/devs/*.md → Qdrant collection ``project_docs`` (default).

Usage::

    idx = DocsIndexer(qdrant_client=qdrant)
    n = await idx.index_docs()
    hits = await idx.search("как поднять dev среду?", limit=5)

Idempotent (sha256 chunk id). Graceful: qdrant_client=None → InMemoryQdrantFallback.
"""

from __future__ import annotations

import hashlib
import re
from pathlib import Path
from typing import Any

from src.backend.core.logging import get_logger

__all__ = ("DocsIndexer", "InMemoryQdrantFallback")

logger = get_logger(__name__)

_DEFAULT_ROOTS: tuple[str, ...] = (
    "CLAUDE.md",
    ".claude/CLAUDE.md",
    "docs/users",
    "docs/devs",
)
_EMBED_DIM = 384  # all-MiniLM-L6-v2 dimension


def _h(text: str) -> str:
    """sha256[:16] — stable chunk id (idempotency anchor)."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:16]


def _embed_hashbased(text: str, dim: int = _EMBED_DIM) -> list[float]:
    """Hash-based embedder (offline/unit fallback). Не ML-grade, но стабильный + детерминированный."""
    vec = [0.0] * dim
    for tok in re.findall(r"\w+", (text or "").lower()):
        vec[
            int(hashlib.md5(tok.encode(), usedforsecurity=False).hexdigest(), 16) % dim
        ] += 1.0  # noqa: S324
    n = sum(v * v for v in vec) ** 0.5
    return [v / n for v in vec] if n > 0 else vec


class _SentenceTransformerEmbedder:
    """Lazy-loaded sentence-transformers embedder with batching."""

    def __init__(self, model_name: str = "all-MiniLM-L6-v2") -> None:
        self._model_name = model_name
        self._model: Any = None

    def _load(self) -> Any:
        if self._model is None:
            try:
                from sentence_transformers import SentenceTransformer

                self._model = SentenceTransformer(self._model_name)
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "sentence_transformers unavailable (%s); fallback to hash-based",
                    exc,
                )
        return self._model

    def encode(self, texts: list[str]) -> list[list[float]]:
        model = self._load()
        if model is None:
            return [_embed_hashbased(t) for t in texts]
        embeddings = model.encode(
            texts, convert_to_tensor=False, batch_size=32, show_progress_bar=False
        )
        return [emb.tolist() for emb in embeddings]


def _cosine(a: list[float], b: list[float]) -> float:
    if not a or not b or len(a) != len(b):
        return 0.0
    dot = sum(x * y for x, y in zip(a, b))
    na = sum(x * x for x in a) ** 0.5
    nb = sum(x * x for x in b) ** 0.5
    return dot / (na * nb) if na and nb else 0.0


def _hit(r: Any) -> dict[str, Any]:
    """Qdrant SearchResult (attr-style) ИЛИ dict → унифицированный hit."""
    if isinstance(r, dict):
        pid, score, payload = r.get("id"), r.get("score"), r.get("payload", {})
    else:
        pid, score, payload = (
            getattr(r, "id", None),
            getattr(r, "score", None),
            getattr(r, "payload", None) or {},
        )
    return {
        "id": str(pid),
        "score": float(score or 0.0),
        "document": (payload or {}).get("document", ""),
        "metadata": {k: v for k, v in (payload or {}).items() if k != "document"},
    }


class InMemoryQdrantFallback:
    """Минимальный in-memory Qdrant-substitute (для unit-tests и dev-light)."""

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
        scored = sorted(
            ((p, _cosine(query_vector, v)) for p, v in vecs.items()),
            key=lambda x: x[1],
            reverse=True,
        )

        class _Hit:
            __slots__ = ("id", "payload", "score")

            def __init__(self, pid: str, score: float, payload: dict[str, Any]) -> None:
                self.id, self.score, self.payload = pid, score, payload

        return [_Hit(p, s, coll[p]) for p, s in scored[:limit]]


class DocsIndexer:
    """Ingest project markdown docs → Qdrant → RAG search.

    Per v15 §10 W5: CLAUDE.md, .claude/CLAUDE.md, docs/users/*.md,
    docs/devs/*.md → Qdrant collection ``project_docs`` (default).
    Idempotent (hash-based id). Graceful: ``qdrant_client is None`` → fallback.
    """

    def __init__(
        self,
        *,
        qdrant_client: Any = None,
        embedding_model: str = "sentence-transformers",
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
        # eager init for sentence-transformers
        if embedding_model == "sentence-transformers":
            self._embedder = _SentenceTransformerEmbedder()

    @property
    def collection_name(self) -> str:
        return self._collection_name

    @property
    def is_fallback(self) -> bool:
        return self._fallback

    def set_embedder(self, embed_fn: Any) -> "DocsIndexer":
        """DI: ``(texts: list[str]) -> list[list[float]]`` (sync/async). Chainable."""
        self._embedder = embed_fn
        return self

    def _ensure_collection(self) -> None:
        if self._collection_ready:
            return
        try:
            self._qdrant.get_collection(self._collection_name)
        except Exception:  # noqa: BLE001 — collection may not exist yet
            try:
                from qdrant_client.models import Distance, VectorParams

                self._qdrant.create_collection(
                    collection_name=self._collection_name,
                    vectors_config=VectorParams(
                        size=_EMBED_DIM, distance=Distance.COSINE
                    ),
                )
            except Exception:  # noqa: BLE001 — fallback API
                self._qdrant.create_collection(self._collection_name)
        self._collection_ready = True

    def discover_docs(self, roots: list[str | Path] | None = None) -> list[Path]:
        """Find all .md files в ``roots``. Default: :data:`_DEFAULT_ROOTS`."""
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
        """Split ``text`` → word-aware chunks of ~``chunk_size`` chars с ``chunk_overlap``.

        Каждый chunk: ``id`` (sha256[:16]), ``text``, ``metadata`` (file, line,
        hash, source_path, chunk_index). Empty/whitespace text → [].
        """
        if not text or not text.strip():
            return []
        step = max(1, self._chunk_size - self._chunk_overlap)
        chunks: list[dict[str, Any]] = []
        idx, start = 0, 0
        while start < len(text):
            end = min(start + self._chunk_size, len(text))
            if end < len(text):
                # look backward for whitespace to avoid breaking words
                while end > start and text[end] not in " \n\r\t":
                    end -= 1
                if end == start:
                    # no whitespace found — force break at chunk_size
                    end = min(start + self._chunk_size, len(text))
            piece = text[start:end].strip()
            if piece:
                # merge tiny last piece into previous chunk
                if (
                    chunks
                    and len(piece) < self._chunk_size * 0.2
                    and len(chunks[-1]["text"]) + 1 + len(piece)
                    <= self._chunk_size * 1.5
                ):
                    merged = chunks[-1]["text"] + " " + piece
                    chunks[-1]["text"] = merged
                    chunks[-1]["id"] = _h(merged)
                    chunks[-1]["metadata"]["hash"] = chunks[-1]["id"]
                else:
                    line_no = text.count("\n", 0, start) + 1
                    chunks.append(
                        {
                            "id": _h(piece),
                            "text": piece,
                            "metadata": {
                                **metadata,
                                "line": line_no,
                                "chunk_index": idx,
                                "hash": _h(piece),
                            },
                        }
                    )
                    idx += 1
            start += step
            if start <= end - self._chunk_size:
                start = end
        return chunks

    async def _embed(self, texts: list[str]) -> list[list[float]]:
        if self._embedder is not None:
            if hasattr(self._embedder, "encode"):
                return self._embedder.encode(texts)
            r = self._embedder(texts)
            if hasattr(r, "__await__"):
                r = await r  # type: ignore[func-returns-value]
            return list(r)
        return [_embed_hashbased(t) for t in texts]

    def _build_points(
        self, chunks: list[dict[str, Any]], vecs: list[list[float]]
    ) -> list[Any]:
        """PointStruct (Qdrant) → dict (fallback) — automatic dispatch."""
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
        except Exception:  # noqa: BLE001 — fallback path
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
        """RAG search: ``query`` → top-N relevant chunks. Empty → ValueError."""
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
        return [_hit(r) for r in results]
