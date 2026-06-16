"""Regression test: core/auth/* use core.logging.get_logger (S93 W4).

Проверяет что 5 файлов в core/auth/ переведены с stdlib logging на
core.logging facade (structured logging, Graylog routing, etc).
"""

from __future__ import annotations

from pathlib import Path

import pytest

PROJECT_ROOT = Path(__file__).resolve().parents[4]

# 5 files, переведённых в S93 W4 codemod.
TARGETS = (
    "src/backend/core/auth/jwt_backend.py",
    "src/backend/core/auth/jwt_blacklist.py",
    "src/backend/core/auth/ldap_client_factory.py",
    "src/backend/core/auth/jwks_cache.py",
    "src/backend/core/auth/mtls_backend.py",
)


@pytest.mark.parametrize("rel_path", TARGETS)
def test_auth_module_uses_core_logger(rel_path: str) -> None:
    """Каждый core/auth модуль должен использовать core.logging facade."""
    src = (PROJECT_ROOT / rel_path).read_text()
    # Должен импортировать get_logger из core.logging
    assert "from src.backend.core.logging import get_logger" in src, (
        f"{rel_path} должен использовать core.logging.get_logger"
    )
    # НЕ должен импортировать stdlib logging напрямую
    assert "import logging" not in src, (
        f"{rel_path} использует stdlib logging напрямую (S93 W4 codemod missed)"
    )
    # НЕ должен использовать logging.getLogger
    assert "logging.getLogger" not in src, (
        f"{rel_path} использует logging.getLogger вместо get_logger"
    )


def test_all_core_auth_modules_use_core_logger() -> None:
    """All core/auth/*.py: NO `import logging` (except saml_backend with stdlib handler)."""
    import re

    auth_dir = PROJECT_ROOT / "src/backend/core/auth"
    # SAML backend использует stdlib (security token XML), это legit
    excluded = {"saml_backend.py", "__init__.py"}
    offenders = []
    for py in auth_dir.glob("*.py"):
        if py.name in excluded:
            continue
        src = py.read_text()
        if re.search(r"^import logging$", src, re.MULTILINE):
            offenders.append(py.name)
    assert not offenders, (
        f"core/auth/* still uses stdlib logging: {offenders}. "
        "Apply S93 W4 codemod pattern."
    )
