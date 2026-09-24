"""RouteBuilder fluent-contract (V5 P2): фиксация публичной поверхности.

Пинирует: (1) инстанцирование и наличие ключевых fluent-методов всех
семейств; (2) контракт модификаторов «до первого step» (ValueError —
осознанный guard, см. with_timeout); (3) размер публичной поверхности
(sanity, чтобы split/migration не терял методы молча).
"""

from __future__ import annotations

import pytest

from src.backend.dsl.builders import RouteBuilder

# Репрезентативные методы по семействам (entity / agent / workflow / policy).
KEY_METHODS = (
    "entity_get",
    "entity_create",
    "saga_lra",
    "call_function",
    "invoke_workflow",
    "with_timeout",
)


def test_route_builder_instantiable() -> None:
    """RouteBuilder создаётся без аргументов."""
    assert isinstance(RouteBuilder(), RouteBuilder)


@pytest.mark.parametrize("method", KEY_METHODS)
def test_key_fluent_methods_present(method: str) -> None:
    """Ключевые fluent-методы присутствуют на билдере."""
    assert hasattr(RouteBuilder(), method), method


def test_public_surface_size_sanity() -> None:
    """Публичная поверхность билдера не «сдувается» молча (sanity ≥ 60)."""
    b = RouteBuilder()
    public = [m for m in dir(b) if not m.startswith("_")]
    assert len(public) >= 60, f"публичных методов стало {len(public)}"


def test_with_timeout_before_first_step_raises() -> None:
    """Модификатор без предыдущего step → ValueError (осознанный guard)."""
    b = RouteBuilder()
    with pytest.raises(ValueError, match="до первого step"):
        b.with_timeout(5)


def test_method_annotations_present() -> None:
    """Ключевые методы имеют return-аннотацию (typed fluent contract)."""
    import inspect

    for method in ("entity_get", "saga_lra", "invoke_workflow"):
        sig = inspect.signature(getattr(RouteBuilder, method))
        assert sig.return_annotation is not inspect.Signature.empty, method
