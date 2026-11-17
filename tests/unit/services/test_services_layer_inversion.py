"""Контракт инверсии слоя ``services`` → ``extensions`` (ADR-0457).

Расширение **отдаёт** свои ресурсы в core-реестр, потребитель в
``src/backend/services/`` **забирает** их по ключу — статического импорта
``extensions.*`` в сервисном слое не остаётся.

Проверяется AST-уровнем (как ``tools/check_layers.py``, но точечно и без
запуска полного скана репозитория).
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

_SERVICE_MODULES = (
    "src.backend.services.io.files",
    "src.backend.services.auth.bootstrap_admin",
    "src.backend.services.integrations.skb",
)


def _module_path(dotted: str) -> Path:
    """Возвращает путь к файлу модуля по его dotted-имени."""
    import importlib

    module = importlib.import_module(dotted)
    assert module.__file__ is not None
    return Path(module.__file__)


@pytest.mark.parametrize("dotted", _SERVICE_MODULES)
def test_service_module_has_no_static_extensions_import(dotted: str) -> None:
    """В сервисном слое нет ни одного статического ``import extensions.*``."""
    tree = ast.parse(_module_path(dotted).read_text(encoding="utf-8"))
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            assert not (node.module or "").startswith("extensions"), (
                f"{dotted}: статический импорт {node.module!r} нарушает ADR-0457"
            )
        elif isinstance(node, ast.Import):
            for alias in node.names:
                assert not alias.name.startswith("extensions"), (
                    f"{dotted}: статический импорт {alias.name!r} нарушает ADR-0457"
                )
