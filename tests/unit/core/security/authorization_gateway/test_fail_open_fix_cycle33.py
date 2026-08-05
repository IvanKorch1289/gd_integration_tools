"""Unit-тесты cycle 33 B-01/B-03 fix: authz fail-open → deny-by-default.

B-01: ``_is_enabled()`` — раньше возвращал ``False`` при исключении из
``get_feature_flag_service()`` → ``authorize()`` дальше делал allow без
проверок (P0). Теперь при исключении — ERROR-лог + return ``True``,
чтобы capability_check ниже остался fail-closed.

B-03: ``check()`` — раньше ``except Exception: pass`` для Casbin/OPA
engine'ов. Теперь — WARNING + ``authz_check_engine_failed_total`` counter.

Покрытие:
* ``_is_enabled`` логирует ERROR и возвращает ``True`` при падении
  feature-flag service;
* ``check()`` логирует WARNING и инкрементит counter при падении
  Casbin engine'а, возвращает ``False`` (default-deny);
* ``check()`` то же для OPA engine'а.

Counter читаем напрямую через ``prometheus_client.Counter._value.get()``
(не через Registry API), чтобы не зависеть от test-isolation helpers.
"""

# ruff: noqa: S101

from __future__ import annotations

import logging

import pytest

from src.backend.core.security.authorization_gateway import (
    AuthorizationGateway,
    authz_check_engine_failed_total,
)
from src.backend.core.security.capabilities.gate import CapabilityGate


@pytest.fixture
def gateway() -> AuthorizationGateway:
    """AuthorizationGateway с минимальным CapabilityGate (без деклараций)."""
    return AuthorizationGateway(capability_gateway=CapabilityGate())


def _counter_value(engine: str) -> float:
    """Текущее значение counter'а для заданного engine.

    Использует ``prometheus_client.Counter._value.get()`` (private API,
    но стабильный с v0.x). Альтернатива — ``.collect()[0].samples``,
    но она требует registry-walk; этот вариант проще и быстрее.
    """
    metric = authz_check_engine_failed_total.labels(engine=engine)
    return metric._value.get()  # noqa: SLF001 — internal prometheus API


class TestIsEnabledFailOpenFix:
    """B-01 fix: ``_is_enabled()`` должен остаться enabled при ошибке feature-flag."""

    def test_authz_is_enabled_logs_on_exception_returns_true(
        self, gateway: AuthorizationGateway, caplog: pytest.LogCaptureFixture
    ) -> None:
        """При падении ``get_feature_flag_service()`` _is_enabled() возвращает True.

        Pre-fix поведение: return False → authorize() дальше делал allow
        без capability_check (P0). Post-fix: ERROR-лог + True → шёл
        нормальный chain (capability_check → fail-closed deny).
        """
        # Конструкторский _enabled=None → путь через feature_flags.
        assert gateway._enabled is None

        def _exploding_service() -> None:
            raise RuntimeError("redis down: feature flag registry unreachable")

        # Monkeypatch на уровне модуля — внутри _is_enabled() lazy import.
        import src.backend.core.feature_flags as feature_flags_module

        original_getter = feature_flags_module.get_feature_flag_service

        def _boom() -> None:
            raise RuntimeError("redis down: feature flag registry unreachable")

        feature_flags_module.get_feature_flag_service = _boom
        try:
            with caplog.at_level(logging.ERROR, logger="core.security.authorization_gateway"):
                result = gateway._is_enabled()
        finally:
            feature_flags_module.get_feature_flag_service = original_getter

        assert result is True, (
            "B-01: при падении feature-flag service _is_enabled() "
            "должен вернуть True, чтобы не пропустить authorize() в "
            "fail-open путь"
        )
        assert any(
            "authz feature-flag lookup failed" in record.message
            for record in caplog.records
        ), "ERROR-лог с описанием деградации обязателен"
        assert any(
            record.levelno == logging.ERROR for record in caplog.records
        ), "должен быть именно ERROR level (не WARNING)"

    def test_authz_is_enabled_constructor_override_takes_precedence(
        self, gateway: AuthorizationGateway
    ) -> None:
        """Конструкторский ``enabled=False`` имеет приоритет над fallback.

        Когда operator явно выставил ``enabled=False`` через конструктор,
        _is_enabled() возвращает False независимо от feature-flag lookup —
        и при исключении НЕ должен инвертироваться в True.
        """
        explicit = AuthorizationGateway(
            capability_gateway=CapabilityGate(), enabled=False
        )
        assert explicit._enabled is False
        # feature-flag service тут не должен вызываться (early return).
        assert explicit._is_enabled() is False

    def test_authz_is_enabled_happy_path_returns_flag_value(
        self, monkeypatch: pytest.MonkeyPatch, gateway: AuthorizationGateway
    ) -> None:
        """Happy-path: feature flag = True → _is_enabled() = True."""
        monkeypatch.setattr(
            "src.backend.core.feature_flags.get_feature_flag_service",
            lambda: _FakeService("authz_gateway_enabled", True),
        )
        assert gateway._is_enabled() is True


class TestCheckEngineFailureWarning:
    """B-03 fix: ``check()`` логирует WARNING + инкрементит counter при ошибке engine'а."""

    def test_check_logs_warning_on_casbin_exception_returns_false(
        self,
        gateway: AuthorizationGateway,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """Casbin engine бросает → WARNING + counter inc + return False."""
        before = _counter_value("casbin")

        def _exploding_casbin(
            subject: str, action: str, resource: str
        ) -> bool | None:
            raise ConnectionError("casbin enforcer socket closed")

        # Monkeypatch на инстансе: метод `_casbin_check` объявлен в
        # AuthorizationGateway, поэтому подменяем bound method.
        gateway._casbin_check = _exploding_casbin  # type: ignore[method-assign]

        with caplog.at_level(
            logging.WARNING, logger="core.security.authorization_gateway"
        ):
            result = gateway.check("alice", "read", "document:1")

        assert result is False, (
            "B-03: при падении Casbin engine'а check() должен "
            "вернуть False (fail-closed default), а не пройти дальше"
        )
        assert any(
            "engine=casbin failed" in record.message for record in caplog.records
        ), "WARNING-лог с engine=casbin обязателен"
        assert any(
            record.levelno == logging.WARNING for record in caplog.records
        )
        assert _counter_value("casbin") == before + 1, (
            "counter authz_check_engine_failed_total{engine=casbin} "
            "должен инкрементироваться ровно на 1"
        )

    def test_check_logs_warning_on_opa_exception_returns_false(
        self,
        gateway: AuthorizationGateway,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """OPA engine бросает → WARNING + counter inc + return False."""
        before = _counter_value("opa")

        def _exploding_opa(
            subject: str,
            action: str,
            resource: str,
            context: dict[str, object] | None,
        ) -> bool | None:
            raise TimeoutError("opa query timeout after 5s")

        gateway._opa_check = _exploding_opa  # type: ignore[method-assign]

        with caplog.at_level(
            logging.WARNING, logger="core.security.authorization_gateway"
        ):
            result = gateway.check("alice", "read", "document:2")

        assert result is False
        assert any(
            "engine=opa failed" in record.message for record in caplog.records
        )
        assert any(
            record.levelno == logging.WARNING for record in caplog.records
        )
        assert _counter_value("opa") == before + 1

    def test_check_in_memory_fallback_short_circuits(
        self, gateway: AuthorizationGateway
    ) -> None:
        """In-memory hit НЕ вызывает engine'и → counter не растёт.

        Sanity check: новая логика не сломала happy-path in-memory путь.
        """
        casbin_before = _counter_value("casbin")
        opa_before = _counter_value("opa")

        gateway.add_policy("alice", "read", "document:3", effect="allow")
        result = gateway.check("alice", "read", "document:3")

        assert result is True
        assert _counter_value("casbin") == casbin_before
        assert _counter_value("opa") == opa_before


class _FakeService:
    """Minimal FeatureFlagService stand-in (только is_enabled)."""

    def __init__(self, key: str, value: bool) -> None:
        self._key = key
        self._value = value

    def is_enabled(self, key: str) -> bool:
        return self._value if key == self._key else False
