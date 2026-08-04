"""Целевые проверки Sprint 5.5 для сужения типов DI-провайдеров.

Проверяется, что два реально существующих высокочастотных provider'а
публикуют конкретные return-типы вместо ``Any`` и сохраняют test-override
семантику. Внутренний тип ``policy_resolver`` также фиксируется AST-проверкой:
публичного ``get_policy_resolver_provider`` в актуальном коде нет.
"""

from __future__ import annotations

import ast
import inspect
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING, assert_type

import pytest

from src.backend.core.di.providers import ai, auth

if TYPE_CHECKING:
    from src.backend.core.ai import AIGateway
    from src.backend.core.auth.jwt_backend import JwtBackend

    assert_type(auth.get_jwt_backend_provider(), JwtBackend)
    assert_type(ai.get_ai_gateway_provider(), AIGateway)


PROVIDER_ANNOTATIONS: tuple[tuple[Callable[[], object], str], ...] = (
    (auth.get_jwt_backend_provider, "JwtBackend"),
    (ai.get_ai_gateway_provider, "AIGateway"),
)


@pytest.mark.unit
@pytest.mark.parametrize(("provider", "expected"), PROVIDER_ANNOTATIONS)
def test_provider_return_annotation_is_concrete(
    provider: Callable[[], object], expected: str
) -> None:
    """Публичный return type provider'а не должен быть ``Any``."""
    annotations = inspect.get_annotations(provider, eval_str=False)
    assert annotations.get("return") == expected
    assert annotations.get("return") != "Any"


@pytest.mark.unit
def test_jwt_provider_override_preserves_runtime_identity() -> None:
    """JWT provider продолжает возвращать установленный test-override."""
    sentinel = object()
    auth.set_jwt_backend_provider(sentinel)
    try:
        assert auth.get_jwt_backend_provider() is sentinel
    finally:
        auth.set_jwt_backend_provider(None)


@pytest.mark.unit
def test_ai_gateway_provider_override_preserves_runtime_identity() -> None:
    """AIGateway provider продолжает возвращать установленный test-override."""
    sentinel = object()
    ai.set_ai_gateway_provider(sentinel)
    try:
        assert ai.get_ai_gateway_provider() is sentinel
    finally:
        ai.set_ai_gateway_provider(None)


@pytest.mark.unit
def test_policy_resolver_local_annotation_is_narrowed() -> None:
    """Builder хранит policy resolver как существующий ``PolicyResolver``-тип."""
    source_path = Path(ai.__file__)
    tree = ast.parse(source_path.read_text(encoding="utf-8"))
    annotations = [
        ast.unparse(node.annotation)
        for node in ast.walk(tree)
        if isinstance(node, ast.AnnAssign)
        and isinstance(node.target, ast.Name)
        and node.target.id == "policy_resolver"
    ]
    assert annotations == ["PolicyResolver | None"]
