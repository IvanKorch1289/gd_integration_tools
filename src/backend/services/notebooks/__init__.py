"""Notebooks — версионируемые заметки на MongoDB (Wave 9.1).

Append-only история версий с restore, REST API и Streamlit-страницей.
"""

from __future__ import annotations as annotations

from src.backend.services.notebooks.models import Notebook, NotebookVersion  # noqa: F401 — re-export
from src.backend.services.notebooks.repository import (
    InMemoryNotebookRepository,
    NotebookRepository,
)
from src.backend.services.notebooks.service import NotebookService, get_notebook_service  # noqa: F401 — re-export

__all__ = (
    "InMemoryNotebookRepository",
    "Notebook",
    "NotebookRepository",
    "NotebookService",
    "NotebookVersion",
    "get_notebook_service",
)
