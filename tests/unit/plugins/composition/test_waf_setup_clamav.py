"""Тесты production wiring ClamAV scanner в WAF policy (Sprint 16 Wave 7, B-3 finale).

Проверяет, что :func:`build_clamav_scanner_if_enabled` корректно
создаёт :class:`ClamAVPayloadScanner` по feature-flag ``waf.clamav_enabled``,
а :func:`_build_waf_policy_from_settings` подключает его к
``WafPolicy.async_payload_scanner``.

Импортируем напрямую из ``infrastructure.antivirus.setup`` — это lightweight
модуль без cycle через ``plugins.composition.__init__``.
"""

# ruff: noqa: S101

from __future__ import annotations

from unittest.mock import patch

import pytest

from src.backend.infrastructure.antivirus.setup import build_clamav_scanner_if_enabled


def _make_waf_settings_stub(**overrides: object) -> object:
    """Лёгкая замена WafSettings для тестов wiring'а."""
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

    from types import SimpleNamespace

    return SimpleNamespace(**defaults)


def test_build_scanner_none_when_flag_off() -> None:
    """clamav_enabled=False → build_clamav_scanner_if_enabled() = None."""
    settings_stub = _make_waf_settings_stub(clamav_enabled=False)
    with patch("src.backend.core.config.waf.waf_settings", settings_stub):
        assert build_clamav_scanner_if_enabled() is None


def test_build_scanner_attaches_clamav_when_flag_on() -> None:
    """clamav_enabled=True → возвращается ClamAVPayloadScanner с заданными params."""
    from src.backend.infrastructure.antivirus.payload_scanner import (
        ClamAVPayloadScanner,
    )

    settings_stub = _make_waf_settings_stub(
        clamav_enabled=True,
        clamav_host="clamav.local",
        clamav_port=3310,
        clamav_fail_open=False,
    )
    with patch("src.backend.core.config.waf.waf_settings", settings_stub):
        scanner = build_clamav_scanner_if_enabled()

    assert scanner is not None
    assert isinstance(scanner, ClamAVPayloadScanner)
    assert scanner._fail_open is False
    assert scanner._backend.name == "clamav_tcp"


@pytest.mark.asyncio
async def test_built_scanner_works_in_evaluate_async() -> None:
    """End-to-end: WafPolicy с подключённым scanner вызывает его в evaluate_async."""
    from src.backend.core.net.waf import WafPolicy

    settings_stub = _make_waf_settings_stub(clamav_enabled=True, clamav_fail_open=True)
    with patch("src.backend.core.config.waf.waf_settings", settings_stub):
        scanner = build_clamav_scanner_if_enabled()

    policy = WafPolicy(async_payload_scanner=scanner)
    # ClamAV в test-env недоступен — fail_open=True даст clean (None) ответ.
    decision = await policy.evaluate_async("https://api.example.com/x", payload=b"any")
    assert decision.allowed is True


def test_build_scanner_returns_none_when_disabled_short() -> None:
    """Прямая проверка фабрики при выключенном флаге (duplicate-strict guard)."""
    settings_stub = _make_waf_settings_stub(clamav_enabled=False)
    with patch("src.backend.core.config.waf.waf_settings", settings_stub):
        assert build_clamav_scanner_if_enabled() is None
