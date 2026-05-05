"""Wiki — full-text поиск по docs/ через Whoosh-reloaded (Wave 10.2)."""

from __future__ import annotations

from src.services.wiki.whoosh_index import Hit, WhooshIndex, get_wiki_index

__all__ = ("Hit", "WhooshIndex", "get_wiki_index")
