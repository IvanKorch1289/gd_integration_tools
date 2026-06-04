#!/usr/bin/env python
"""ingest_docs_to_rag.py — CLI для индексации project markdown docs в Qdrant.

Sprint 40 W5 (v15 §10): use-case "RAG over project documentation".
Использует :class:`DocsIndexer` из ``src.backend.services.ai.rag.docs_indexer``.

Запуск::

    # 1) Реальный Qdrant (env QDRANT_URL=http://localhost:6333).
    .venv/bin/python scripts/ingest_docs_to_rag.py

    # 2) Кастомные roots + embedding model.
    .venv/bin/python scripts/ingest_docs_to_rag.py \\
        --roots CLAUDE.md docs/users --collection my_docs \\
        --embedding-model text-embedding-3-large

    # 3) Dry-run (печать плана без индексации).
    .venv/bin/python scripts/ingest_docs_to_rag.py --dry-run

    # 4) Fallback (без Qdrant, in-memory store; для smoke-test).
    .venv/bin/python scripts/ingest_docs_to_rag.py --no-qdrant --query "dev среда"
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys
from pathlib import Path
from typing import Any

# Добавляем корень проекта в sys.path для запуска вне venv-sitepackages.
_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from src.backend.services.ai.rag.docs_indexer import (  # noqa: E402
    DocsIndexer,
    InMemoryQdrantFallback,
)

logger = logging.getLogger("ingest_docs_to_rag")


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Ingest project markdown docs (CLAUDE.md, .claude/, docs/) → Qdrant для RAG.",
    )
    parser.add_argument(
        "--roots", nargs="+", default=None,
        help="Кастомные roots (paths/dirs). Default: CLAUDE.md, .claude/CLAUDE.md, docs/users, docs/devs",
    )
    parser.add_argument("--collection", default="project_docs", help="Qdrant collection name")
    parser.add_argument("--embedding-model", default="text-embedding-3-small")
    parser.add_argument("--chunk-size", type=int, default=512)
    parser.add_argument("--chunk-overlap", type=int, default=50)
    parser.add_argument(
        "--qdrant-url", default=None,
        help="Qdrant URL (default: http://localhost:6333 если задан QDRANT_URL)",
    )
    parser.add_argument(
        "--no-qdrant", action="store_true",
        help="Не подключаться к Qdrant (in-memory fallback; полезно для smoke-test)",
    )
    parser.add_argument("--dry-run", action="store_true", help="Печать плана без индексации")
    parser.add_argument(
        "--query", default=None,
        help="После индексации выполнить RAG-поиск с этим query (smoke-test)",
    )
    parser.add_argument("--limit", type=int, default=5, help="Top-N для search (default: 5)")
    parser.add_argument("-v", "--verbose", action="store_true")
    return parser.parse_args()


def _build_qdrant_client(args: argparse.Namespace) -> Any:
    """DI: реальный Qdrant или fallback."""
    if args.no_qdrant:
        return None
    try:
        from qdrant_client import QdrantClient  # type: ignore[import-not-found]
    except ImportError:
        logger.warning("qdrant-client недоступен → fallback")
        return None
    url = args.qdrant_url or "http://localhost:6333"
    try:
        return QdrantClient(url=url, timeout=5)
    except Exception as exc:  # noqa: BLE001
        logger.warning("QdrantClient(%s) failed: %s → fallback", url, exc)
        return None


async def _run(args: argparse.Namespace) -> int:
    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
    )

    qdrant = _build_qdrant_client(args)
    indexer = DocsIndexer(
        qdrant_client=qdrant,
        embedding_model=args.embedding_model,
        collection_name=args.collection,
        chunk_size=args.chunk_size,
        chunk_overlap=args.chunk_overlap,
    )

    # DI: если есть OpenAI-ключ, подключаем настоящий embedder.
    try:
        from src.backend.services.ai.embedding_providers import (  # type: ignore[import-not-found]
            OpenAIEmbeddingProvider,
        )

        if not indexer.is_fallback and not args.no_qdrant:
            indexer.set_embedder(OpenAIEmbeddingProvider().embed)
            logger.info("Используем OpenAIEmbeddingProvider для embed")
    except Exception:  # noqa: BLE001
        logger.debug("OpenAI embedder недоступен → offline hash-based fallback")

    # 1) Discover.
    paths = indexer.discover_docs(args.roots)
    if not paths:
        logger.error("Не найдено .md файлов в roots=%s", args.roots or "default")
        return 2
    total_size = sum(p.stat().st_size for p in paths if p.is_file())
    logger.info("Discovered: %d .md файлов, %d bytes total", len(paths), total_size)

    if args.dry_run:
        for p in paths[:20]:
            print(f"  {p}")
        if len(paths) > 20:
            print(f"  ... и ещё {len(paths) - 20}")
        print(f"DRY-RUN: would ingest {len(paths)} files → collection={args.collection}")
        return 0

    # 2) Index.
    n = await indexer.index_docs(args.roots)
    logger.info("Indexed: %d chunks → collection=%s (fallback=%s)", n, args.collection, indexer.is_fallback)
    print(f"OK: {n} chunks indexed → {args.collection}")

    # 3) Optional search.
    if args.query:
        hits = await indexer.search(args.query, limit=args.limit)
        print(f"\nSearch '{args.query}' (top {args.limit}):")
        for h in hits:
            score = h.get("score", 0.0)
            doc = h.get("document", "")[:80].replace("\n", " ")
            meta = h.get("metadata", {}).get("file", "?")
            print(f"  [{score:.3f}] {meta}: {doc}")
        if not hits:
            print("  (no matches)")
    return 0


def main() -> int:
    args = _parse_args()
    try:
        return asyncio.run(_run(args))
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    raise SystemExit(main())
