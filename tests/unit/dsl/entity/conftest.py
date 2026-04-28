"""Bootstrap для unit-тестов DSL entity-процессоров (Wave 11)."""

from __future__ import annotations

import os
from pathlib import Path

from src.core.config.constants import consts

# Глубина: tests/unit/dsl/entity/conftest.py -> parents[4] == корень репозитория.
_REPO_ROOT = Path(__file__).resolve().parents[4]
if (_REPO_ROOT / "config.yml").exists():
    consts.ROOT_DIR = _REPO_ROOT

os.environ.setdefault("LOG_HOST", "")
os.environ.setdefault("LOG_UDP_PORT", "1")
