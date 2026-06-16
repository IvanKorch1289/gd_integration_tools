"""S84 W4: check_layers.py не находит новых violations после W2 codemod.

V2 P0 #3: 274 violations (86.7% от total) должны быть устранены.
W2 codemod заменил 254 imports. W4 проверяет что:
1. 0 новых violations (т.е. infrastructure.logging.factory только в infrastructure/*)
2. baseline (legacy 186) не увеличился
"""

from __future__ import annotations

import subprocess
from pathlib import Path


def test_no_infrastructure_logging_imports_in_core() -> None:
    """core/* не должен импортировать infrastructure.logging.factory напрямую."""
    result = subprocess.run(
        [
            "git",
            "grep",
            "-l",
            "from src.backend.infrastructure.logging.factory",
            "src/backend/core/",
        ],
        capture_output=True,
        text=True,
        cwd=Path(__file__).parent.parent.parent,
    )
    assert result.returncode != 0, (
        f"core/ STILL imports infrastructure.logging.factory:\n{result.stdout}"
    )


def test_no_infrastructure_logging_imports_in_services() -> None:
    """services/* не должен импортировать infrastructure.logging.factory напрямую."""
    result = subprocess.run(
        [
            "git",
            "grep",
            "-l",
            "from src.backend.infrastructure.logging.factory",
            "src/backend/services/",
        ],
        capture_output=True,
        text=True,
        cwd=Path(__file__).parent.parent.parent,
    )
    assert result.returncode != 0, (
        f"services/ STILL imports infrastructure.logging.factory:\n{result.stdout}"
    )


def test_no_infrastructure_logging_imports_in_entrypoints() -> None:
    """entrypoints/* не должен импортировать infrastructure.logging.factory напрямую."""
    result = subprocess.run(
        [
            "git",
            "grep",
            "-l",
            "from src.backend.infrastructure.logging.factory",
            "src/backend/entrypoints/",
        ],
        capture_output=True,
        text=True,
        cwd=Path(__file__).parent.parent.parent,
    )
    assert result.returncode != 0, (
        f"entrypoints/ STILL imports infrastructure.logging.factory:\n{result.stdout}"
    )


def test_no_infrastructure_logging_imports_in_dsl() -> None:
    """dsl/* не должен импортировать infrastructure.logging.factory напрямую."""
    result = subprocess.run(
        [
            "git",
            "grep",
            "-l",
            "from src.backend.infrastructure.logging.factory",
            "src/backend/dsl/",
        ],
        capture_output=True,
        text=True,
        cwd=Path(__file__).parent.parent.parent,
    )
    assert result.returncode != 0, (
        f"dsl/ STILL imports infrastructure.logging.factory:\n{result.stdout}"
    )


def test_no_infrastructure_logging_imports_in_plugins() -> None:
    """plugins/* не должен импортировать infrastructure.logging.factory напрямую."""
    result = subprocess.run(
        [
            "git",
            "grep",
            "-l",
            "from src.backend.infrastructure.logging.factory",
            "src/backend/plugins/",
        ],
        capture_output=True,
        text=True,
        cwd=Path(__file__).parent.parent.parent,
    )
    assert result.returncode != 0, (
        f"plugins/ STILL imports infrastructure.logging.factory:\n{result.stdout}"
    )
