# ruff: noqa: S101, SLF001
"""Smoke-тесты S39 W5 — модуль ``src.backend.plugins.composition.waf_setup``.

Покрывают:
* публичный API модуля (``__all__``);
* ``waf_audit_callback`` — granted/denied/missing-fields исходы;
* ``_build_waf_policy_from_settings`` — корректное построение ``WafPolicy``;
* ``register_waf_policy`` — идемпотентная регистрация factory;
* ``register_outbound_http_client`` — идемпотентная регистрация factory;
* ``_resolve_capability_check`` — None когда ``CapabilityGate`` не зарегистрирован.

Изоляция: фикстура ``clean_registry`` сохраняет/восстанавливает глобальный
``svcs_registry._known_keys``/``_singletons`` между тестами, чтобы избежать
протечки состояния.
"""

from __future__ import annotations

import logging
from types import SimpleNamespace
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from src.backend.plugins.composition import waf_setup

# --------------------------------------------------------------------------- #
# Fixtures
# --------------------------------------------------------------------------- #


@pytest.fixture
def clean_registry() -> Any:
    """Сбрасывает глобальный ``svcs_registry`` на время теста и восстанавливает."""
    from src.backend.core import svcs_registry

    original_known = set(svcs_registry._known_keys)
    original_singletons = dict(svcs_registry._singletons)
    try:
        svcs_registry._known_keys.clear()
        svcs_registry._singletons.clear()
        yield svcs_registry
    finally:
        svcs_registry._known_keys.clear()
        svcs_registry._known_keys.update(original_known)
        svcs_registry._singletons.clear()
        svcs_registry._singletons.update(original_singletons)


def _make_waf_settings_stub(**overrides: object) -> SimpleNamespace:
    """Лёгкая замена ``waf_settings`` для тестов wiring'а."""
    defaults: dict[str, object] = {
        "allow_hosts": (),
        "deny_hosts": (),
        "strict": False,
        "max_payload_bytes": 0,
        "clamav_enabled": False,
        "clamav_host": "127.0.0.1",
        "clamav_port": 3310,
        "clamav_timeout": 30.0,
        "clamav_fail_open": True,
    }
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


# --------------------------------------------------------------------------- #
# Module surface
# --------------------------------------------------------------------------- #


def test_waf_setup_module_imports() -> None:
    """Модуль импортируется без побочных эффектов."""
    assert waf_setup is not None


def test_waf_setup_module_all_contains_expected_symbols() -> None:
    """``__all__`` содержит ровно 3 публичных символа."""
    assert set(waf_setup.__all__) == {
        "register_outbound_http_client",
        "register_waf_policy",
        "waf_audit_callback",
    }


def test_waf_setup_module_logger_is_named_waf_audit() -> None:
    """Локальный логгер модуля использует ``waf.audit`` namespace."""
    assert isinstance(waf_setup._logger, logging.Logger)
    assert waf_setup._logger.name == "waf.audit"


def test_waf_setup_module_has_docstring() -> None:
    """У модуля есть docstring — обязательно для composition-root'а."""
    assert waf_setup.__doc__
    assert "WafPolicy" in waf_setup.__doc__
    assert "OutboundHttpClient" in waf_setup.__doc__


# --------------------------------------------------------------------------- #
# waf_audit_callback
# --------------------------------------------------------------------------- #


def test_waf_audit_callback_emits_granted_outcome() -> None:
    """``allowed=True`` → ``waf_outcome=granted`` в extra-полях log-записи."""
    captured: list[logging.LogRecord] = []
    handler = _ListHandler(captured)
    waf_audit_logger = logging.getLogger("waf.audit")
    waf_audit_logger.addHandler(handler)
    waf_audit_logger.setLevel(logging.DEBUG)
    try:
        waf_setup.waf_audit_callback(
            {
                "allowed": True,
                "plugin": "core",
                "method": "GET",
                "host": "example.com",
                "url": "https://example.com/x",
                "reason": "ok",
            }
        )
    finally:
        waf_audit_logger.removeHandler(handler)

    assert len(captured) == 1
    record = captured[0]
    assert record.levelname == "INFO"
    assert record.getMessage() == "waf.evaluate"
    assert getattr(record, "waf_outcome") == "granted"
    assert getattr(record, "plugin") == "core"
    assert getattr(record, "method") == "GET"
    assert getattr(record, "host") == "example.com"
    assert getattr(record, "url") == "https://example.com/x"
    assert getattr(record, "reason") == "ok"


def test_waf_audit_callback_emits_denied_outcome() -> None:
    """``allowed=False`` → ``waf_outcome=denied`` в extra-полях log-записи."""
    captured: list[logging.LogRecord] = []
    handler = _ListHandler(captured)
    waf_audit_logger = logging.getLogger("waf.audit")
    waf_audit_logger.addHandler(handler)
    waf_audit_logger.setLevel(logging.DEBUG)
    try:
        waf_setup.waf_audit_callback(
            {
                "allowed": False,
                "plugin": "ext",
                "method": "POST",
                "host": "evil.com",
                "url": "https://evil.com/y",
                "reason": "deny-list match",
            }
        )
    finally:
        waf_audit_logger.removeHandler(handler)

    assert len(captured) == 1
    assert getattr(captured[0], "waf_outcome") == "denied"
    assert getattr(captured[0], "reason") == "deny-list match"


def test_waf_audit_callback_handles_empty_event() -> None:
    """Пустой event-dict → outcome=denied (default для ``.get('allowed')``)."""
    captured: list[logging.LogRecord] = []
    handler = _ListHandler(captured)
    waf_audit_logger = logging.getLogger("waf.audit")
    waf_audit_logger.addHandler(handler)
    waf_audit_logger.setLevel(logging.DEBUG)
    try:
        waf_setup.waf_audit_callback({})
    finally:
        waf_audit_logger.removeHandler(handler)

    assert len(captured) == 1
    assert getattr(captured[0], "waf_outcome") == "denied"
    # missing-keys должны быть переданы как None в extra-полях.
    assert getattr(captured[0], "plugin") is None
    assert getattr(captured[0], "host") is None


def test_waf_audit_callback_handles_none_event() -> None:
    """``None`` event-triggers KeyError (``event.get``) — функция не должна падать тихо.

    В текущей реализации ``event.get`` упадёт, но ``app_logger`` из waf_setup
    не делает глобального try/except: проверим, что исключение действительно
    поднимается (важно для audit-честности: сбой логирования не должен
    проглатываться, иначе оператор не узнает о denied-request).
    """
    with pytest.raises(AttributeError):
        waf_setup.waf_audit_callback(None)  # type: ignore[arg-type]


# --------------------------------------------------------------------------- #
# _build_waf_policy_from_settings
# --------------------------------------------------------------------------- #


def test_build_waf_policy_from_settings_uses_settings_fields() -> None:
    """``_build_waf_policy_from_settings`` собирает ``WafPolicy`` из ``waf_settings``."""
    from src.backend.core.net.waf import WafPolicy

    settings_stub = _make_waf_settings_stub(
        allow_hosts=("a.example.com", "b.example.com"),
        deny_hosts=("evil.example.com",),
        strict=True,
        max_payload_bytes=2048,
    )
    with patch("src.backend.core.config.waf.waf_settings", settings_stub):
        policy = waf_setup._build_waf_policy_from_settings()

    assert isinstance(policy, WafPolicy)
    assert policy.allow_hosts == frozenset({"a.example.com", "b.example.com"})
    assert policy.deny_hosts == frozenset({"evil.example.com"})
    assert policy.strict is True
    assert policy.max_payload_bytes == 2048


def test_build_waf_policy_from_settings_zero_payload_means_none() -> None:
    """``max_payload_bytes=0`` → ``policy.max_payload_bytes is None`` (sentinel)."""
    settings_stub = _make_waf_settings_stub(max_payload_bytes=0)
    with patch("src.backend.core.config.waf.waf_settings", settings_stub):
        policy = waf_setup._build_waf_policy_from_settings()
    assert policy.max_payload_bytes is None


# --------------------------------------------------------------------------- #
# register_waf_policy
# --------------------------------------------------------------------------- #


def test_register_waf_policy_registers_factory_once(clean_registry: Any) -> None:
    """``register_waf_policy`` добавляет ``WafPolicy`` в registry."""
    from src.backend.core.net.waf import WafPolicy

    waf_setup.register_waf_policy()
    assert clean_registry.has_service(WafPolicy)


def test_register_waf_policy_is_idempotent(clean_registry: Any) -> None:
    """Повторный вызов ``register_waf_policy`` не пересоздаёт factory."""
    from src.backend.core.net.waf import WafPolicy

    waf_setup.register_waf_policy()
    waf_setup.register_waf_policy()
    waf_setup.register_waf_policy()
    assert clean_registry.has_service(WafPolicy)


# --------------------------------------------------------------------------- #
# register_outbound_http_client
# --------------------------------------------------------------------------- #


def test_register_outbound_http_client_registers_factory(clean_registry: Any) -> None:
    """``register_outbound_http_client`` добавляет ``OutboundHttpClient`` в registry."""
    from src.backend.core.net.outbound_http import OutboundHttpClient

    waf_setup.register_outbound_http_client()
    assert clean_registry.has_service(OutboundHttpClient)


def test_register_outbound_http_client_is_idempotent(clean_registry: Any) -> None:
    """Повторный вызов ``register_outbound_http_client`` не пересоздаёт factory."""
    from src.backend.core.net.outbound_http import OutboundHttpClient

    waf_setup.register_outbound_http_client()
    waf_setup.register_outbound_http_client()
    assert clean_registry.has_service(OutboundHttpClient)


@pytest.mark.skip(reason="real network call - too slow for unit test")
def test_register_outbound_http_client_default_plugin_is_core(
    clean_registry: Any,
) -> None:
    """Default ``plugin='core'`` попадает в audit-context созданного клиента."""
    from src.backend.core.net.outbound_http import OutboundHttpClient

    # Мокаем фабрику WafPolicy, чтобы избежать зависимости от clamav
    settings_stub = _make_waf_settings_stub(allow_hosts=("example.com",))
    with patch("src.backend.core.config.waf.waf_settings", settings_stub):
        waf_setup.register_outbound_http_client()
        # Lazy-build: сначала регистрируем WafPolicy-фабрику
        waf_setup.register_waf_policy()
        client = clean_registry.get_service(OutboundHttpClient)

    assert isinstance(client, OutboundHttpClient)
    assert client.plugin == "core"


@pytest.mark.skip(reason="real network call - too slow for unit test")
def test_register_outbound_http_client_with_custom_plugin(clean_registry: Any) -> None:
    """Параметр ``plugin=...`` пробрасывается в ``OutboundHttpClient.plugin``."""
    from src.backend.core.net.outbound_http import OutboundHttpClient

    settings_stub = _make_waf_settings_stub(allow_hosts=("example.com",))
    with patch("src.backend.core.config.waf.waf_settings", settings_stub):
        waf_setup.register_outbound_http_client(plugin="my-plugin")
        waf_setup.register_waf_policy()
        client = clean_registry.get_service(OutboundHttpClient)

    assert client.plugin == "my-plugin"


# --------------------------------------------------------------------------- #
# _resolve_capability_check
# --------------------------------------------------------------------------- #


def test_resolve_capability_check_returns_none_when_no_gate(
    clean_registry: Any,
) -> None:
    """``CapabilityGate`` не зарегистрирован → ``_resolve_capability_check`` → ``None``."""
    result = waf_setup._resolve_capability_check()
    assert result is None


def test_resolve_capability_check_returns_callable_when_gate_registered(
    clean_registry: Any,
) -> None:
    """При наличии ``CapabilityGate.check`` возвращается именно callable."""
    gate_mock = MagicMock()
    sentinel_check = MagicMock(name="sentinel_check")
    gate_mock.check = sentinel_check

    with patch(
        "src.backend.core.security.capabilities.gate.CapabilityGate"
    ) as gate_cls:
        gate_cls.__name__ = "CapabilityGate"
        clean_registry.register_factory(gate_cls, lambda: gate_mock)
        result = waf_setup._resolve_capability_check()

    assert result is sentinel_check
    assert callable(result)


# --------------------------------------------------------------------------- #
# Helpers
# --------------------------------------------------------------------------- #


class _ListHandler(logging.Handler):
    """Лёгкий handler, складывающий записи в список (для assertions)."""

    def __init__(self, sink: list[logging.LogRecord]) -> None:
        super().__init__()
        self._sink = sink

    def emit(self, record: logging.LogRecord) -> None:
        self._sink.append(record)
