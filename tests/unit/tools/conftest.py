"""Conftest для тестов scripts/utilities в tools/ (Sprint 9 K5 W3).

``tools/`` не установлен как пакет в pyproject — добавляем корень
проекта в sys.path локально для этой суб-папки тестов.
"""

from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[3]
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))
