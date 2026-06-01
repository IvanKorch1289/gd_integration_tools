"""Регрессионные тесты для T2.5 (S17 DoD-3): YAML-injection защита.

Контекст:
    DSL workflow YAML loader (:mod:`src.backend.dsl.workflow.yaml_io`)
    должен использовать ruamel.yaml ``typ="safe"`` для парсинга
    untrusted источников. Unsafe-теги (``!!python/object/apply``,
    ``!!python/object/new``, ``!!python/name`` и т. п.) должны отвергаться
    конструктором.

Wave: ``[wave:s17/k1-w6-yaml-safeload]``.
"""

from __future__ import annotations

import pytest

from src.backend.core.config.features import feature_flags
from src.backend.dsl.workflow.yaml_io import from_yaml


@pytest.fixture(autouse=True)
def _enable_yaml_round_trip(monkeypatch: pytest.MonkeyPatch) -> None:
    """Активировать ``workflow_yaml_round_trip`` для регрессионных тестов."""
    monkeypatch.setattr(feature_flags, "workflow_yaml_round_trip", True)


def test_yaml_safe_load_rejects_python_object_apply() -> None:
    """``!!python/object/apply:os.system`` должен быть отвергнут safe-mode YAML loader.

    Проверка защиты от CVE-style code injection через YAML
    deserialization unsafe Python-object тегов.
    """
    payload = """!!python/object/apply:os.system ["echo pwned"]
"""
    with pytest.raises(Exception):
        from_yaml(payload)


def test_yaml_safe_load_rejects_python_object_new() -> None:
    """``!!python/object/new`` тоже отвергается safe-mode."""
    payload = """!!python/object/new:os.system ["echo pwned"]
"""
    with pytest.raises(Exception):
        from_yaml(payload)


def test_yaml_safe_load_rejects_python_name_reference() -> None:
    """``!!python/name:`` (reference на builtin/module) отвергается safe-mode."""
    payload = """target: !!python/name:os.system
"""
    with pytest.raises(Exception):
        from_yaml(payload)


def test_yaml_safe_load_rejects_python_module_import() -> None:
    """``!!python/module:`` (импорт модуля) отвергается safe-mode."""
    payload = """target: !!python/module:os
"""
    with pytest.raises(Exception):
        from_yaml(payload)
