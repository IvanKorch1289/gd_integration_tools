"""Регрессия SECURITY-P0-005: placeholder degradation handler = UNBOUND (F-L).

Контекст
---------
``_register_default_degradation_features``
(``plugins/composition/setup_infra/lifecycle.py``) регистрирует типовые
features с обработчиками-заглушками ``_unsupported_full`` /
``_unsupported_degraded``, которые бросают ``NotImplementedError``.
Докстринг функции прямо признаёт: «Real-handler'ы — заглушки».

Но до фикса :class:`FeatureState` не знал состояния «не привязан»:
все такие features стартовали в ``HEALTHY``, и снимок
``/tech/degradation/snapshot`` отдавал:

    {"ai.llm_call": {"state": "healthy", "samples": 0, "error_rate": 0.0}}

То есть «успех» для того, что ни разу не выполнялось — implicit success.

Контракт после фикса
--------------------
* заглушка (``bound=False``) стартует в :attr:`FeatureState.UNBOUND`;
* в снимке UNBOUND даёт ``bound: false`` и ``error_rate: null``, а не ``0.0``;
* настоящий feature (``bound=True``, значение по умолчанию) работает как раньше —
  ``healthy`` / ``error_rate: 0.0``;
* контракт ``record_outcome`` для незарегистрированного feature не менялся.
"""

from __future__ import annotations

from typing import Any

import pytest

from src.backend.core.resilience.graceful_degradation import (
    DegradationFeature,
    FeatureState,
    GracefulDegradationRegistry,
)

pytestmark = pytest.mark.unit


async def _ok(*_args: Any, **_kwargs: Any) -> str:
    """Рабочий обработчик."""
    return "ok"


async def _stub(*_args: Any, **_kwargs: Any) -> str:
    """Заглушка — соответствует ``_unsupported_*`` в production wiring."""
    raise NotImplementedError("handler не зарегистрирован")


def _feature(name: str, *, bound: bool) -> DegradationFeature:
    """Собрать feature для теста."""
    return DegradationFeature(
        name=name,
        full_handler=_ok if bound else _stub,
        degraded_handler=_ok if bound else _stub,
        bound=bound,
    )


class TestPlaceholderIsUnbound:
    """Заглушка не должна выглядеть рабочей."""

    def test_placeholder_starts_unbound(self) -> None:
        """Регистрация заглушки даёт UNBOUND, а не HEALTHY."""
        registry = GracefulDegradationRegistry()
        registry.register(_feature("ai.llm_call", bound=False))

        assert registry.get_state("ai.llm_call") is FeatureState.UNBOUND

    def test_bound_feature_still_healthy(self) -> None:
        """Настоящий feature по-прежнему стартует в HEALTHY (обратная совместимость)."""
        registry = GracefulDegradationRegistry()
        registry.register(_feature("real.feature", bound=True))

        assert registry.get_state("real.feature") is FeatureState.HEALTHY

    def test_default_bound_is_true(self) -> None:
        """Значение по умолчанию — bound=True, чтобы не ломать существующие регистрации."""
        feature = DegradationFeature(name="x", full_handler=_ok, degraded_handler=_ok)

        assert feature.bound is True

    def test_snapshot_marks_unbound_and_nulls_error_rate(self) -> None:
        """Снимок не показывает «нулевую ошибку» у того, что не выполнялось."""
        registry = GracefulDegradationRegistry()
        registry.register(_feature("ai.llm_call", bound=False))
        registry.register(_feature("real.feature", bound=True))

        snapshot = registry.snapshot()

        assert snapshot["ai.llm_call"] == {
            "state": "unbound",
            "bound": False,
            "samples": 0,
            "error_rate": None,
        }, f"Заглушка всё ещё выглядит здоровой: {snapshot['ai.llm_call']}"
        assert snapshot["real.feature"]["state"] == "healthy"
        assert snapshot["real.feature"]["bound"] is True
        assert snapshot["real.feature"]["error_rate"] == 0.0

    @pytest.mark.asyncio
    async def test_unbound_placeholder_fails_closed_when_called(self) -> None:
        """Вызов заглушки падает (fail-closed), а не возвращает успешный результат."""
        registry = GracefulDegradationRegistry()
        registry.register(_feature("ai.llm_call", bound=False))

        handler = registry.get_handler("ai.llm_call")
        assert handler is not None

        with pytest.raises(NotImplementedError):
            await handler()

    def test_all_production_default_features_are_unbound(self) -> None:
        """Реальная production-регистрация помечает заглушки как unbound."""
        from src.backend.core.resilience.graceful_degradation import (
            get_graceful_degradation_registry,
        )
        from src.backend.plugins.composition.setup_infra.lifecycle import (
            _register_default_degradation_features,
        )

        registry = get_graceful_degradation_registry()
        _register_default_degradation_features()

        snapshot = registry.snapshot()
        default_names = [
            "ai.llm_call",
            "rag.retrieval",
            "external.api_call",
            "cache.lookup",
        ]
        for name in default_names:
            assert name in snapshot, f"Default feature {name} не зарегистрирован"
            assert snapshot[name]["bound"] is False, (
                f"{name} зарегистрирован как привязанный, хотя обработчики — заглушки"
            )
            assert snapshot[name]["state"] == "unbound", (
                f"{name} не помечен unbound: {snapshot[name]}"
            )


class TestUnrelatedContractPreserved:
    """Правка не должна менять соседние контракты."""

    @pytest.mark.asyncio
    async def test_unknown_feature_noop_still_healthy(self) -> None:
        """Контракт ``record_outcome`` для незарегистрированного feature сохранён."""
        registry = GracefulDegradationRegistry()

        state = await registry.record_outcome("missing", success=False)

        assert state is FeatureState.HEALTHY
