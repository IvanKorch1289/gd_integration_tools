"""Bootstrap для unit-тестов notebooks.

Общий env-bootstrap вынесен в ``tests/unit/conftest.py``. Специфики нет.

Notebooks-сервис не цепляет Redis при импорте (используется ленивый
``MongoNotebookRepository`` с fallback на InMemory).
"""

from __future__ import annotations
