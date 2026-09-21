"""Регрессионный тест для T4.9 (S17 DoD-7): K-TLS-1..3.

Контекст:
    Согласно V15 Security Constraints (V1, hotfix Sprint 0): в проде
    запрещено использование ``ssl.CERT_NONE`` и ``check_hostname=False``.
    Все клиенты ДОЛЖНЫ использовать ``ssl.create_default_context()`` +
    ``verify_mode=CERT_REQUIRED`` для защиты от MITM-атак.

Wave: ``[wave:s17/k1-w1-tls-cert-required]``.
"""

from __future__ import annotations

import ast
import re
from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[2] / "src" / "backend"

#: Шаблоны, явно указывающие на ``CERT_NONE``-присвоение или
#: отключение hostname-проверки.
ASSIGNMENT_PATTERNS = (
    re.compile(r"verify_mode\s*=\s*ssl\.CERT_NONE"),
    re.compile(r"check_hostname\s*=\s*False"),
)


def _iter_python_files(root: Path) -> list[Path]:
    """Вернуть все ``*.py`` файлы под ``root`` без ``__pycache__``."""
    return [p for p in root.rglob("*.py") if "__pycache__" not in p.parts]


def _string_literal_lines(text: str) -> set[int]:
    """Вернуть номера строк, попадающих внутрь string-литералов.

    Используется для отсева docstring/комментариев из grep-результата —
    в них pattern фигурирует как **запрет**, не как реальное присвоение.
    """
    try:
        tree = ast.parse(text)
    except SyntaxError:
        return set()

    lines: set[int] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, str):
            start = getattr(node, "lineno", None)
            end = getattr(node, "end_lineno", None)
            if start is not None and end is not None:
                lines.update(range(start, end + 1))
    return lines


def test_no_cert_none_assignment_in_backend() -> None:
    """В реальном коде ``src/backend/`` отсутствуют ``CERT_NONE``-assignment.

    Допускаются только упоминания внутри string-литералов (docstring,
    error-messages) — там паттерн фигурирует как запрет, а не как
    реальное присвоение.
    """
    offenders: list[tuple[Path, int, str]] = []

    for file_path in _iter_python_files(BACKEND_ROOT):
        try:
            text = file_path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue

        literal_lines = _string_literal_lines(text)

        for lineno, line in enumerate(text.splitlines(), start=1):
            stripped = line.strip()
            # Пропустить comment-only строки и строки внутри string-литералов
            if stripped.startswith("#") or lineno in literal_lines:
                continue

            for pattern in ASSIGNMENT_PATTERNS:
                if pattern.search(line):
                    offenders.append((file_path, lineno, line.rstrip()))

    assert not offenders, (
        "Найдены реальные присвоения ssl.CERT_NONE / check_hostname=False:\n"
        + "\n".join(f"  {p}:{ln}: {src}" for p, ln, src in offenders)
    )


def test_email_imap_uses_safe_default_context() -> None:
    """``email_imap.py`` использует ``ssl.create_default_context()`` + CERT_REQUIRED.

    Контрактная гарантия: ``_ssl_context()`` явно выставляет ``verify_mode``
    в ``CERT_REQUIRED`` и ``check_hostname=True`` — без условий и opt-out.
    """
    src_path = BACKEND_ROOT / "infrastructure" / "sources" / "email_imap.py"
    email_imap_src = src_path.read_text(encoding="utf-8")

    assert "ssl.create_default_context()" in email_imap_src
    assert "ssl.CERT_REQUIRED" in email_imap_src
    # check_hostname явно True в _ssl_context
    assert "check_hostname = True" in email_imap_src


@pytest.mark.parametrize(
    "ssl_module_attr", ["create_default_context", "PROTOCOL_TLS_CLIENT"]
)
def test_ssl_module_has_safe_defaults(ssl_module_attr: str) -> None:
    """Smoke-test: stdlib ``ssl`` модуль содержит safe-default API."""
    import ssl as ssl_module

    assert hasattr(ssl_module, ssl_module_attr)
