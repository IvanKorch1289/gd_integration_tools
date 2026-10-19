"""Tests for ``src.backend.dsl.builders.base._protocols._core``.

S3-3 / M2-#21, W9 P2-13 split: core RouteBuilder contracts.
"""

from __future__ import annotations

import inspect

from src.backend.dsl.builders.base._protocols import _core as mod
from src.backend.dsl.builders.base._protocols._core import (
    _RouteCore,
    _RouteProcessorSteps,
    _shares_prefix,
)


class TestSharesPrefix:
    """_shares_prefix helper — common prefix length >= n."""

    def test_identical_strings(self) -> None:
        assert _shares_prefix("hello", "hello") is True

    def test_different_strings(self) -> None:
        assert _shares_prefix("foo", "bar") is False

    def test_case_insensitive(self) -> None:
        # "ABC" vs "abc" — общий prefix длиной 3 (case-insensitive)
        assert _shares_prefix("ABC", "abc") is True

    def test_short_first_string(self) -> None:
        # len(a) < n → False
        assert _shares_prefix("ab", "abcdef") is False

    def test_short_second_string(self) -> None:
        # len(b) < n → False
        assert _shares_prefix("abcdef", "ab") is False

    def test_custom_n(self) -> None:
        # n=2 → достаточно 2 одинаковых символа в начале
        assert _shares_prefix("abxxx", "abyyy", n=2) is True
        assert _shares_prefix("axxxx", "byyyy", n=2) is False

    def test_exactly_n_chars(self) -> None:
        # "abc" vs "abd" — первые 2 символа совпадают, 3-й нет
        # При n=2 → True, при n=3 → False
        assert _shares_prefix("abc", "abd", n=2) is True
        assert _shares_prefix("abc", "abd", n=3) is False

    def test_default_n_is_three(self) -> None:
        import inspect

        sig = inspect.signature(_shares_prefix)
        assert sig.parameters["n"].default == 3


class TestRouteProcessorSteps:
    """_RouteProcessorSteps — protocol for processor chain."""

    def test_protocol_importable(self) -> None:
        assert _RouteProcessorSteps is not None

    def test_has_add_processor(self) -> None:
        assert hasattr(_RouteProcessorSteps, "_add_processor")

    def test_has_add_lazy(self) -> None:
        assert hasattr(_RouteProcessorSteps, "_add_lazy")

    def test_add_processor_signature(self) -> None:
        sig = inspect.signature(_RouteProcessorSteps._add_processor)
        params = list(sig.parameters.keys())
        # 'self' + 'processor' (метод протокола)
        assert params == ["self", "processor"]

    def test_add_lazy_signature(self) -> None:
        sig = inspect.signature(_RouteProcessorSteps._add_lazy)
        params = list(sig.parameters.keys())
        # 'self' + 'module' + 'cls_name' + '**kwargs'
        assert "self" in params
        assert "module" in params
        assert "cls_name" in params

    def test_runtime_checkable(self) -> None:
        # _RouteProcessorSteps помечен @runtime_checkable

        class _FakeRoute:
            def _add_processor(self, processor):  # type: ignore[no-untyped-def]
                return self

            def _add_lazy(self, module, cls_name, **kwargs):  # type: ignore[no-untyped-def]
                return self

        route = _FakeRoute()
        assert isinstance(route, _RouteProcessorSteps)


class TestRouteCore:
    """_RouteCore — protocol for route identity + output."""

    def test_protocol_importable(self) -> None:
        assert _RouteCore is not None

    def test_has_route_id(self) -> None:
        assert hasattr(_RouteCore, "route_id")

    def test_route_id_is_property(self) -> None:
        # route_id — property
        assert isinstance(_RouteCore.route_id, property)

    def test_has_to(self) -> None:
        assert hasattr(_RouteCore, "to")

    def test_has_log(self) -> None:
        assert hasattr(_RouteCore, "log")

    def test_log_signature_defaults(self) -> None:
        sig = inspect.signature(_RouteCore.log)
        params = sig.parameters
        # level default "info", message default ""
        assert params["level"].default == "info"
        assert params["message"].default == ""

    def test_to_signature_accepts_kwargs(self) -> None:
        sig = inspect.signature(_RouteCore.to)
        params = sig.parameters
        # to(sink, **kwargs)
        assert "sink" in params
        # **kwargs присутствует
        has_var_keyword = any(
            p.kind == inspect.Parameter.VAR_KEYWORD for p in params.values()
        )
        assert has_var_keyword

    def test_runtime_checkable(self) -> None:
        class _FakeRoute:
            @property
            def route_id(self) -> str:
                return "test_route"

            def to(self, sink: str, **kwargs):  # type: ignore[no-untyped-def]
                return self

            def log(self, level: str = "info", message: str = ""):  # type: ignore[no-untyped-def]
                return self

        route = _FakeRoute()
        assert isinstance(route, _RouteCore)


class TestRuntimeCheckableBehavior:
    """Проверка runtime_checkable на non-conformant types."""

    def test_dict_is_not_route_steps(self) -> None:
        assert not isinstance({}, _RouteProcessorSteps)

    def test_none_is_not_route_steps(self) -> None:
        assert not isinstance(None, _RouteProcessorSteps)

    def test_int_is_not_route_core(self) -> None:
        assert not isinstance(42, _RouteCore)

    def test_str_is_not_route_core(self) -> None:
        assert not isinstance("hello", _RouteCore)


class TestModuleImport:
    """Smoke import + exports."""

    def test_module_imports(self) -> None:
        from src.backend.dsl.builders.base._protocols import _core as m

        assert m is mod

    def test_all_exports(self) -> None:
        # _RouteCore, _RouteProcessorSteps — основные
        assert hasattr(mod, "_RouteCore")
        assert hasattr(mod, "_RouteProcessorSteps")
        assert hasattr(mod, "_shares_prefix")