"""DSL search utilities (S10 K3 W5)."""

from __future__ import annotations

from src.backend.dsl.search.processor_search import (  # noqa: F401 — re-export
    ProcessorSearch,
    SearchResult,
    tokenize,
)

__all__ = ("ProcessorSearch", "SearchResult", "tokenize")
