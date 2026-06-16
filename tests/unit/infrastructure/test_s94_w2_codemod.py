"""Regression test: S94 W2 codemod — saml_backend, http/__init__ (dead DEBUG), http_httpx.

- core/auth/saml_backend.py: getLogger → get_logger (S93 W4 incorrectly
  excluded it; S94 W2 fixed).
- infrastructure/clients/transport/http/__init__.py: удалён dead
  `from logging import DEBUG` (DEBUG использовался только в импорте).
- infrastructure/clients/transport/http_httpx.py: явный комментарий что
  `import logging` retained for `logging.DEBUG` constant (tenacity hook).
"""

from __future__ import annotations

from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]


def test_saml_backend_uses_core_logger() -> None:
    src = (PROJECT_ROOT / "src/backend/core/auth/saml_backend.py").read_text()
    assert "from src.backend.core.logging import get_logger" in src
    assert "import logging" not in src
    assert "logging.getLogger" not in src


def test_http_init_no_dead_debug_import() -> None:
    """`from logging import DEBUG` удалён — не использовался."""
    src = (
        PROJECT_ROOT / "src/backend/infrastructure/clients/transport/http/__init__.py"
    ).read_text()
    assert "from logging import DEBUG" not in src
    assert "import logging" not in src


def test_http_httpx_keeps_stdlib_for_DEBUG_constant() -> None:
    """http_httpx.py: `import logging` retained for tenacity hook.

    Uses ``before_sleep_log(logger, logging.DEBUG)`` — `logging.DEBUG`
    is a stdlib constant. Не swap'им, оставляем комментарий.
    """
    src = (
        PROJECT_ROOT / "src/backend/infrastructure/clients/transport/http_httpx.py"
    ).read_text()
    assert "import logging" in src
    assert "logging.DEBUG" in src
    # Уже factory.get_logger
    assert "from src.backend.infrastructure.logging.factory import get_logger" in src
    # НЕТ logging.getLogger
    assert "logging.getLogger" not in src
