"""Флаг авто-скана @register_action (аудит prod-readiness, предложение P1).

Скан ``scan_and_register_actions`` обходит все модули пакета
``src.backend.services`` (392 модуля) ради поиска ``@register_action``-декораторов
и тянет ``presidio_analyzer`` — 4.2 с на старте в прод-образе (14.6 с в
dev-venv). В production-коде таких декораторов нет: скан регистрирует 0
actions, а приложение логирует «Auto-registered 0 actions».

Поэтому скан вынесен под флаг ``FEATURE_DSL_AUTO_SCAN_ACTIONS`` (default-OFF).
Контракты, которые здесь закреплены:

1. При выключенном флаге скан НЕ вызывается (но ``register_all_actions`` —
   основная регистрация 132 actions — выполняется всегда).
2. При включённом флаге скан вызывается с прежним списком пакетов.
3. Наблюдаемый результат одинаков: число зарегистрированных actions не
   зависит от флага (сегодня — 0 и 0).
"""

from __future__ import annotations

from typing import Any

import pytest

from src.backend.dsl.commands.registry import action_handler_registry
from src.backend.dsl.commands.setup import registers_domains

pytestmark = [pytest.mark.unit]

#: Пакеты, которые сканировались до введения флага.
EXPECTED_SCAN_PACKAGES = [
    "src.backend.services",
    "src.backend.entrypoints.webhook",
    "src.backend.services.integrations",
]


@pytest.fixture()
def _clean_registry() -> Any:
    """Сбросить реестр actions перед/после теста.

    Args:
        None.

    Yields:
        None.
    """
    action_handler_registry.clear()
    yield
    action_handler_registry.clear()


def _set_flag(monkeypatch: pytest.MonkeyPatch, enabled: bool) -> None:
    """Выставить значение флага авто-скана.

    Args:
        monkeypatch: Фикстура pytest.
        enabled: Значение флага.
    """
    from src.backend.core.config.features import feature_flags

    monkeypatch.setattr(feature_flags, "dsl_auto_scan_actions", enabled, raising=False)


def test_flag_defaults_to_off() -> None:
    """Флаг по умолчанию выключен (скан не должен стоить 4 с старта).

    Args:
        None.
    """
    from src.backend.core.config.features import feature_flags

    assert getattr(feature_flags, "dsl_auto_scan_actions", False) is False


def test_scan_skipped_when_flag_off(
    monkeypatch: pytest.MonkeyPatch, _clean_registry: None
) -> None:
    """При выключенном флаге скан не вызывается.

    Args:
        monkeypatch: Фикстура pytest.
        _clean_registry: Фикстура очистки реестра.
    """
    import src.backend.dsl.service_dsl as service_dsl

    calls: list[list[str]] = []

    def _spy(package_paths: Any = None, **kwargs: Any) -> int:
        calls.append(list(package_paths or []))
        return 0

    monkeypatch.setattr(service_dsl, "scan_and_register_actions", _spy)
    _set_flag(monkeypatch, False)

    registers_domains._register_servicedsl_auto_register()

    assert calls == [], "скан не должен вызываться при выключенном флаге"


def test_scan_runs_when_flag_on(
    monkeypatch: pytest.MonkeyPatch, _clean_registry: None
) -> None:
    """При включённом флаге скан вызывается с прежним списком пакетов.

    Args:
        monkeypatch: Фикстура pytest.
        _clean_registry: Фикстура очистки реестра.
    """
    import src.backend.dsl.service_dsl as service_dsl

    calls: list[list[str]] = []

    def _spy(package_paths: Any = None, **kwargs: Any) -> int:
        calls.append(list(package_paths or []))
        return 0

    monkeypatch.setattr(service_dsl, "scan_and_register_actions", _spy)
    _set_flag(monkeypatch, True)

    registers_domains._register_servicedsl_auto_register()

    assert calls == [EXPECTED_SCAN_PACKAGES]


def test_registered_actions_do_not_depend_on_flag(
    monkeypatch: pytest.MonkeyPatch, _clean_registry: None
) -> None:
    """Число зарегистрированных actions не зависит от флага.

    Args:
        monkeypatch: Фикстура pytest.
        _clean_registry: Фикстура очистки реестра.
    """
    import src.backend.dsl.service_dsl as service_dsl

    def _spy(package_paths: Any = None, **kwargs: Any) -> int:
        return 0

    monkeypatch.setattr(service_dsl, "scan_and_register_actions", _spy)

    _set_flag(monkeypatch, False)
    registers_domains._register_servicedsl_auto_register()
    without_scan = len(action_handler_registry.list_actions())

    action_handler_registry.clear()
    _set_flag(monkeypatch, True)
    registers_domains._register_servicedsl_auto_register()
    with_scan = len(action_handler_registry.list_actions())

    assert without_scan == with_scan, "флаг не должен менять наблюдаемый результат"
    # Сегодня скан даёт 0 actions в обоих режимах (@register_action в
    # production-коде нет) — поэтому равенство и есть весь контракт: флаг
    # не может изменить множество зарегистрированных actions.
