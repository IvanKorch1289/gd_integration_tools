"""Notebooks — версионируемые заметки на MongoDB (Wave 9.1).

Append-only история версий с restore, REST API и Streamlit-страницей.
"""

from __future__ import annotations

from src.backend.services.notebooks.models import (  # noqa: F401 — re-export
    Notebook,
    NotebookVersion,
)
from src.backend.services.notebooks.repository import (
    InMemoryNotebookRepository,
    NotebookRepository,
)
from src.backend.services.notebooks.service import (  # noqa: F401 — re-export
    NotebookService,
    get_notebook_service,
)

__all__ = (
    "InMemoryNotebookRepository",
    "Notebook",
    "NotebookRepository",
    "NotebookService",
    "NotebookVersion",
    "get_notebook_service",
)
