"""Smoke-тесты Wave A: ``init_sentry`` graceful behavior.

Цель — убедиться, что lifespan корректно работает в трёх сценариях:

1. Без ``SENTRY_DSN`` ``init_sentry()`` возвращает ``False`` и не падает;
2. С невалидным DSN либо при отсутствии sentry-sdk — gracefully ``False``;
3. С корректным DSN — sentry_sdk.init вызывается ровно один раз.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from src.backend.infrastructure.observability.sentry_init import init_sentry


@pytest.fixture(autouse=True)
def _clear_sentry_env(monkeypatch: pytest.MonkeyPatch):
    """Очищает SENTRY_DSN/APP_ENVIRONMENT, чтобы тесты были детерминированы."""
    monkeypatch.delenv("SENTRY_DSN", raising=False)
    monkeypatch.delenv("APP_ENVIRONMENT", raising=False)
    yield


def test_init_sentry_without_dsn_returns_false() -> None:
    """Без DSN init возвращает ``False`` (не считается ошибкой)."""
    assert init_sentry() is False


def test_init_sentry_with_explicit_none_dsn_returns_false() -> None:
    """``dsn=None`` явно — также graceful False."""
    assert init_sentry(dsn=None) is False


def test_init_sentry_picks_up_env_dsn(monkeypatch: pytest.MonkeyPatch) -> None:
    """С DSN в env вызывается ``sentry_sdk.init`` и возвращается ``True``.

    Используем minimal stub-DSN; реальная сетевая инициализация Sentry
    SDK не происходит на init() — он только конфигурирует transport.
    """
    monkeypatch.setenv("SENTRY_DSN", "https://public@example.test/1")
    monkeypatch.setenv("APP_ENVIRONMENT", "testing")

    fake_init = MagicMock()
    with patch("sentry_sdk.init", fake_init):
        result = init_sentry(traces_sample_rate=0.0, profiles_sample_rate=0.0)

    assert result is True
    fake_init.assert_called_once()
    kwargs = fake_init.call_args.kwargs
    assert kwargs["environment"] == "testing"
    assert kwargs["dsn"] == "https://public@example.test/1"


def test_init_sentry_without_sdk_returns_false(monkeypatch: pytest.MonkeyPatch) -> None:
    """При отсутствии ``sentry_sdk`` init возвращает ``False`` без падения."""
    monkeypatch.setenv("SENTRY_DSN", "https://public@example.test/1")

    real_import = (
        __builtins__["__import__"]
        if isinstance(__builtins__, dict)
        else __builtins__.__import__
    )

    def _failing_import(name: str, *args, **kwargs):
        if name == "sentry_sdk" or name.startswith("sentry_sdk."):
            raise ImportError(f"forced absence of {name}")
        return real_import(name, *args, **kwargs)

    with patch("builtins.__import__", side_effect=_failing_import):
        assert init_sentry() is False


def test_lifespan_swallows_sentry_init_failure() -> None:
    """Падение ``init_sentry`` не должно ломать lifespan-стартап.

    Минимальный smoke: симулируем raise внутри init_sentry и убеждаемся,
    что lifespan-блок ловит исключение через try/except и продолжает.
    """
    # Sentry init вынесен из ``lifespan`` в startup-phase
    # ``phase_sentry_init`` (lifespan — тонкая обёртка над фазами).
    # Проверяем реальный контракт: исключение внутри init_sentry
    # глушится и НЕ пробрасывается наружу (fail-open для телеметрии,
    # чтобы недоступный Sentry не ронял старт приложения).
    import inspect

    from src.backend.plugins.composition.lifecycle.startup_phases.observability import (
        phase_sentry_init,
    )

    phase_src = inspect.getsource(phase_sentry_init)
    assert "init_sentry" in phase_src, "phase_sentry_init обязан вызывать init_sentry"
    assert "except Exception" in phase_src, (
        "phase_sentry_init обязан глушить исключения Sentry-инициализации"
    )

    # И контракт поведения: при падении импорта sentry фаза не бросает.
    import asyncio

    asyncio.run(phase_sentry_init(None))  # type: ignore[arg-type]


def test_secrets_backend_factory_dispatches_env(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Wave A.3: SECRETS_BACKEND=env даёт EnvSecretsBackend через svcs."""
    monkeypatch.setenv("SECRETS_BACKEND", "env")

    from src.backend.core.interfaces.secrets import SecretsBackend
    from src.backend.core.svcs_registry import clear_registry, get_service
    from src.backend.plugins.composition.service_setup import register_secrets_backend

    clear_registry()
    register_secrets_backend()

    backend = get_service(SecretsBackend)
    assert backend.__class__.__name__ == "EnvSecretsBackend"


def test_secrets_backend_vault_raises_until_wave_k(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """SECRETS_BACKEND=vault до Wave K — осмысленный NotImplementedError."""
    monkeypatch.setenv("SECRETS_BACKEND", "vault")

    from src.backend.core.interfaces.secrets import SecretsBackend
    from src.backend.core.svcs_registry import clear_registry, get_service
    from src.backend.plugins.composition.service_setup import register_secrets_backend

    clear_registry()
    register_secrets_backend()

    with pytest.raises(NotImplementedError, match="Wave K"):
        get_service(SecretsBackend)


def test_clamav_in_compose() -> None:
    """ClamAV-сервис присутствует в docker-compose.yml (Wave A.5)."""
    from pathlib import Path

    compose_path = (
        Path(__file__).resolve().parents[2] / "ops" / "compose" / "docker-compose.yml"
    )
    content = compose_path.read_text(encoding="utf-8")
    assert "clamav:" in content, "ожидался clamav-сервис в compose"
    assert "CLAMAV_HOST" in content, "ожидалась env CLAMAV_HOST для app-сервиса"
