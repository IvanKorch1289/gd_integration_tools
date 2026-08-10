"""RAG-утилиты уровня ai/ (in-project docs ingestion, retrieval).

Sprint 40 W5 (v15 §10 RAG over project documentation):
- :class:`DocsIndexer` — ingest CLAUDE.md, .claude/CLAUDE.md, docs/users/*.md,
  docs/devs/*.md → Qdrant collection ``project_docs`` (default).
"""

from __future__ import annotations as annotations

from src.backend.services.ai.rag.project_docs import DocsIndexer, InMemoryQdrantFallback  # noqa: F401 — re-export

__all__ = ("DocsIndexer", "InMemoryQdrantFallback")
