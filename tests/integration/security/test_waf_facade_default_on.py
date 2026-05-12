"""Integration-тест: WAF Phase-2 default ON (ADR-0053).

Проверяет, что:
* :attr:`WafSettings.outbound_via_facade` теперь по умолчанию True;
* свежий :class:`WafSettings()` без env-override отражает Phase-2 значение;
* доступ через ``waf_settings`` singleton тоже Phase-2.
"""

from __future__ import annotations

from src.backend.core.config.waf import WafSettings, waf_settings


def test_waf_settings_default_phase2_enabled() -> None:
    """Default constructor возвращает Phase-2 значение `outbound_via_facade=True`."""
    settings = WafSettings()
    assert settings.outbound_via_facade is True


def test_waf_singleton_phase2_enabled() -> None:
    """Глобальный singleton ``waf_settings`` тоже Phase-2."""
    assert waf_settings.outbound_via_facade is True


def test_waf_strict_still_off_by_default() -> None:
    """`strict` остаётся False — flip strict-mode выполняется отдельным ADR."""
    settings = WafSettings()
    assert settings.strict is False


def test_waf_can_be_explicitly_disabled() -> None:
    """Phase-1 поведение остаётся доступным через явный ``False`` override."""
    settings = WafSettings(outbound_via_facade=False)
    assert settings.outbound_via_facade is False
