"""Notebooks — версионируемые заметки на MongoDB (Wave 9.1).

Append-only история версий с restore, REST API и Streamlit-страницей.
"""

from __future__ import annotations

from src.services.notebooks.models import Notebook, NotebookVersion
from src.services.notebooks.repository import (
    InMemoryNotebookRepository,
    NotebookRepository,
)
from src.services.notebooks.service import NotebookService, get_notebook_service

__all__ = (
    "Notebook",
    "NotebookVersion",
    "NotebookRepository",
    "InMemoryNotebookRepository",
    "NotebookService",
    "get_notebook_service",
)
