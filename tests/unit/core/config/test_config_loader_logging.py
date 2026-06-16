"""S98 W4 — stdlib logging cleanup: config_loader.py uses core.logging."""

from __future__ import annotations


def test_config_loader_no_stdlib_logging() -> None:
    """``core/config/config_loader.py`` не использует stdlib ``logging``."""
    from pathlib import Path

    p = Path("src/backend/core/config/config_loader.py")
    src = p.read_text()
    # Per S95 W3 rule: stdlib logging should be replaced with core.logging
    assert "import logging\n" not in src and "import logging" not in src, (
        f"{p} still uses stdlib 'import logging'. Use core.logging instead."
    )
    # И не вызывает logging.getLogger
    assert "logging.getLogger" not in src, (
        f"{p} still uses 'logging.getLogger'. Use core.logging.get_logger."
    )
    # Должен использовать core.logging facade
    assert "core.logging import get_logger" in src, (
        f"{p} should use 'from src.backend.core.logging import get_logger'"
    )
