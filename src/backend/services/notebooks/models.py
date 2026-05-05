"""Pydantic-модели Notebook — re-export из core/models/.

DTO перенесены в ``src.core.models.notebooks`` (W6.6), здесь
сохраняется re-export для обратной совместимости импортёров.
"""

from src.core.models.notebooks import Notebook, NotebookVersion

__all__ = ("Notebook", "NotebookVersion")
