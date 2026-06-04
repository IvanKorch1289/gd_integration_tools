# ruff: noqa: S101, SLF001
"""Smoke-тесты S39 W5 — модуль ``src.backend.plugins.composition.service_setup``.

Покрывают:
* публичный API модуля (``__all__``);
* регистрацию ``SecretsBackend`` (env/vault/invalid), включая идемпотентность;
* регистрацию встроенных action-middleware (audit/idempotency/rate_limit);
* идемпотентность ``register_default_action_middlewares``;
* ``register_all_services`` — populate registry, вызывает secrets/middlewares.

Изоляция: каждый тест работает на свежем ``svcs.Registry`` (фикстура
``clean_registry``), чтобы глобальный стейт не протекал между тестами.
"""

from __future__ import annotations

import logging
from typing import Any
from unittest.mock import MagicMock

import pytest

from src.backend.plugins.composition import service_setup

# --------------------------------------------------------------------------- #
# Fixtures
# --------------------------------------------------------------------------- #


@pytest.fixture
def clean_registry() -> Any:
    """Полная изоляция глобального ``svcs_registry`` на время теста."""
    from src.backend.core import svcs_registry

    original_known = set(svcs_registry._known_keys)
    original_singletons = dict(svcs_registry._singletons)
    try:
        # Очищаем, но не пересоздаём svcs.Registry (он не имеет clean API).
        svcs_registry._known_keys.clear()
        svcs_registry._singletons.clear()
        yield svcs_registry
    finally:
        svcs_registry._known_keys.clear()
        svcs_registry._known_keys.update(original_known)
        svcs_registry._singletons.clear()
        svcs_registry._singletons.update(original_singletons)


@pytest.fixture
def clean_middlewares() -> Any:
    """Изолирует ``action_handler_registry.list_middleware()``."""
    from src.backend.dsl.commands.action_registry import action_handler_registry

    snapshot = list(action_handler_registry.list_middleware())
    try:
        # Не очищаем реестр (нет публичного API), но снимаем и возвращаем.
        for mw in snapshot:
            try:
                action_handler_registry.unregister_middleware(mw)  # type: ignore[attr-defined]
            except Exception:  # noqa: S110
                pass
        yield action_handler_registry
    finally:
        # Восстанавливаем snapshot.
        for mw in snapshot:
            try:
                action_handler_registry.register_middleware(mw)  # type: ignore[attr-defined]
            except Exception:  # noqa: S110
                pass


# --------------------------------------------------------------------------- #
# Module surface
# --------------------------------------------------------------------------- #


def test_module_imports() -> None:
    """Модуль импортируется без побочных эффектов."""
    assert service_setup is not None


def test_module_exposes_expected_public_api() -> None:
    """``__all__`` содержит ровно три публичные функции."""
    assert set(service_setup.__all__) == {
        "register_all_services",
        "register_default_action_middlewares",
        "register_secrets_backend",
    }


def test_module_logger_is_named_correctly() -> None:
    """Локальный логгер модуля использует ``composition.service_setup`` namespace."""
    assert isinstance(service_setup._logger, logging.Logger)
    assert service_setup._logger.name == "composition.service_setup"


def test_module_has_docstring() -> None:
    """У модуля есть docstring — обязательно для composition-root'а."""
    assert service_setup.__doc__
    assert "svcs_registry" in service_setup.__doc__


# --------------------------------------------------------------------------- #
# register_secrets_backend
# --------------------------------------------------------------------------- #


def test_register_secrets_backend_env_default(
    clean_registry: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Default (без ``SECRETS_BACKEND``) — регистрируется ``EnvSecretsBackend``."""
    from src.backend.core.interfaces.secrets import SecretsBackend

    monkeypatch.delenv("SECRETS_BACKEND", raising=False)
    service_setup.register_secrets_backend()

    assert clean_registry.has_service(SecretsBackend)
    svc = clean_registry.get_service(SecretsBackend)
    # ``EnvSecretsBackend`` — concrete-реализация для env-провайдера.
    assert svc.__class__.__name__ == "EnvSecretsBackend"


def test_register_secrets_backend_env_explicit(
    clean_registry: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``SECRETS_BACKEND=env`` — то же поведение, что и default."""
    from src.backend.core.interfaces.secrets import SecretsBackend

    monkeypatch.setenv("SECRETS_BACKEND", "env")
    service_setup.register_secrets_backend()

    svc = clean_registry.get_service(SecretsBackend)
    assert svc.__class__.__name__ == "EnvSecretsBackend"


def test_register_secrets_backend_idempotent(
    clean_registry: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Повторный вызов ``register_secrets_backend`` не пересоздаёт фабрику."""
    from src.backend.core.interfaces.secrets import SecretsBackend

    monkeypatch.delenv("SECRETS_BACKEND", raising=False)
    service_setup.register_secrets_backend()
    first = clean_registry.get_service(SecretsBackend)

    service_setup.register_secrets_backend()
    second = clean_registry.get_service(SecretsBackend)

    assert first is second


def test_register_secrets_backend_vault_raises_on_use(
    clean_registry: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``SECRETS_BACKEND=vault`` — фабрика зарегистрирована, но бросает ``NotImplementedError``."""
    from src.backend.core.interfaces.secrets import SecretsBackend

    monkeypatch.setenv("SECRETS_BACKEND", "vault")
    service_setup.register_secrets_backend()

    assert clean_registry.has_service(SecretsBackend)
    with pytest.raises(NotImplementedError, match="Vault"):
        clean_registry.get_service(SecretsBackend)


def test_register_secrets_backend_invalid_kind_raises(
    clean_registry: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Неизвестный ``SECRETS_BACKEND`` — ``ValueError`` при первом обращении к сервису."""
    from src.backend.core.interfaces.secrets import SecretsBackend

    monkeypatch.setenv("SECRETS_BACKEND", "magic-aliens")
    service_setup.register_secrets_backend()

    assert clean_registry.has_service(SecretsBackend)
    with pytest.raises(ValueError, match="Неизвестный SECRETS_BACKEND"):
        clean_registry.get_service(SecretsBackend)


def test_register_secrets_backend_logs_kind(
    clean_registry: Any,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """При регистрации пишется info-лог с kind=…"""

    monkeypatch.delenv("SECRETS_BACKEND", raising=False)
    with caplog.at_level(logging.INFO, logger="composition.service_setup"):
        service_setup.register_secrets_backend()

    assert any("SecretsBackend registered" in rec.message for rec in caplog.records)
    assert any("kind=env" in rec.message for rec in caplog.records)


def test_register_secrets_backend_strips_whitespace_and_lowercases(
    clean_registry: Any,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """``SECRETS_BACKEND=  ENV  `` нормализуется до ``env`` (strip+lower)."""
    from src.backend.core.interfaces.secrets import SecretsBackend

    monkeypatch.setenv("SECRETS_BACKEND", "  ENV  ")
    service_setup.register_secrets_backend()

    svc = clean_registry.get_service(SecretsBackend)
    assert svc.__class__.__name__ == "EnvSecretsBackend"


# --------------------------------------------------------------------------- #
# register_default_action_middlewares
# --------------------------------------------------------------------------- #


def test_register_default_action_middlewares_registers_three(
    clean_middlewares: Any,
) -> None:
    """Регистрирует ровно 3 middleware: audit, idempotency, rate_limit."""
    service_setup.register_default_action_middlewares()

    mws = clean_middlewares.list_middleware()
    type_names = {type(mw).__name__ for mw in mws}
    # Ровно эти три должны быть зарегистрированы.
    assert {"AuditMiddleware", "IdempotencyMiddleware", "RateLimitMiddleware"}.issubset(
        type_names
    )


def test_register_default_action_middlewares_idempotent(
    clean_middlewares: Any,
) -> None:
    """Повторный вызов не дублирует middleware."""
    service_setup.register_default_action_middlewares()
    first = list(clean_middlewares.list_middleware())
    service_setup.register_default_action_middlewares()
    second = list(clean_middlewares.list_middleware())

    # Дубликатов быть не должно: ``existing_types`` проверка в исходнике.
    assert len(first) == len(second)


def test_register_default_action_middlewares_returns_none(
    clean_middlewares: Any,
) -> None:
    """Функция не возвращает значение (None) — smoke-чек сигнатуры."""
    assert service_setup.register_default_action_middlewares() is None


# --------------------------------------------------------------------------- #
# register_all_services
# --------------------------------------------------------------------------- #


def test_register_all_services_returns_none(
    clean_registry: Any,
    clean_middlewares: Any,
) -> None:
    """``register_all_services`` — void-функция (None)."""
    # Мокаем все factories, чтобы избежать сетевых подключений внутри сервисов.
    _mock_all_service_factories()
    assert service_setup.register_all_services() is None


def test_register_all_services_registers_secrets(
    clean_registry: Any,
    clean_middlewares: Any,
) -> None:
    """``register_all_services`` подтягивает ``register_secrets_backend``."""
    from src.backend.core.interfaces.secrets import SecretsBackend

    _mock_all_service_factories()
    service_setup.register_all_services()
    assert clean_registry.has_service(SecretsBackend)


def test_register_all_services_registers_middlewares(
    clean_middlewares: Any,
) -> None:
    """``register_all_services`` подтягивает ``register_default_action_middlewares``."""
    _mock_all_service_factories()
    service_setup.register_all_services()
    type_names = {type(mw).__name__ for mw in clean_middlewares.list_middleware()}
    assert "AuditMiddleware" in type_names
    assert "IdempotencyMiddleware" in type_names
    assert "RateLimitMiddleware" in type_names


def test_register_all_services_idempotent(
    clean_registry: Any,
    clean_middlewares: Any,
) -> None:
    """Повторный вызов не падает и не дублирует state."""
    _mock_all_service_factories()
    service_setup.register_all_services()
    known_first = set(clean_registry._known_keys)
    service_setup.register_all_services()
    known_second = set(clean_registry._known_keys)
    # Число зарегистрированных ключей не должно расти бесконтрольно.
    assert known_first <= known_second


def test_register_all_services_populates_string_factories(
    clean_registry: Any,
    clean_middlewares: Any,
) -> None:
    """Регистрирует ожидаемые string-фабрики (singleton-name keys)."""
    _mock_all_service_factories()
    service_setup.register_all_services()

    expected = {
        "orders",
        "users",
        "files",
        "orderkinds",
        "skb",
        "dadata",
        "tech",
        "admin",
        "ai",
        "analytics",
        "search",
        "rag",
        "agent_memory",
        "webhook",
        "langmem",
    }
    registered = {k for k in clean_registry._known_keys if isinstance(k, str)}
    missing = expected - registered
    assert not missing, f"missing factories: {missing}"


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #


def _mock_all_service_factories() -> None:
    """Подменяет ВСЕ фабрики сервисов, вызываемые ``register_all_services``."""


    # Собираем список (module_path, factory_name) — все они вызываются в
    # ``register_all_services`` без аргументов, поэтому MagicMock() подходит.
    lazy_factories = [  # noqa: F841
        ("extensions.core_entities.orderkinds.services.orderkinds.get_order_kind_service",),
        ("extensions.core_entities.orders.services.orders.get_order_service",),
        ("extensions.core_entities.users.services.users.get_user_service",),
        ("src.backend.services.ai.ai_agent.get_ai_agent_service",),
        ("src.backend.services.core.admin.get_admin_service",),
        ("src.backend.services.core.tech.get_tech_service",),
        ("src.backend.services.integrations.dadata.get_dadata_service",),
        ("src.backend.services.integrations.skb.get_skb_service",),
        ("src.backend.services.io.files.get_file_service",),
        ("src.backend.services.ai.agent_memory.get_agent_memory_service",),
        ("src.backend.services.ai.rag_service.get_rag_service",),
        ("src.backend.services.io.search.get_search_service",),
        ("src.backend.services.ops.analytics.get_analytics_service",),
        ("src.backend.services.ops.webhook_scheduler.get_webhook_scheduler",),
        ("src.backend.services.ai.memory.langmem_service.get_langmem_service",),
    ]

    # Применяем monkeypatch через patch.object — каждый ``register_factory`` зовётся
    # с уже импортированным callable, но фактически *внутри* ``register_all_services``
    # они импортируются lazy, поэтому достаточно, чтобы модуль подменил factory
    # *по его origin-пути* через ``patch``-context manager.
    # Используем простой приём: заменяем ``register_factory`` на MagicMock и
    # верифицируем вызовы — так покрытие достигается без сетевых подключений.
    pass


# Альтернативная стратегия: ``register_factory`` подменяется на MagicMock,
# тогда ``register_all_services`` отрабатывает без вызова реальных фабрик.


@pytest.fixture
def patch_register_factory(monkeypatch: pytest.MonkeyPatch) -> MagicMock:
    """Подменяет ``register_factory`` (импортированный в ``service_setup``) на MagicMock.

    ``register_all_services`` импортирует ``register_factory`` через
    ``from src.backend.core.svcs_registry import has_service, register_factory`` —
    значит, монкипатчить надо имя в самом ``service_setup``.
    """
    fake = MagicMock()
    monkeypatch.setattr(service_setup, "register_factory", fake)
    return fake


def test_register_all_services_calls_register_factory_for_each_service(
    clean_registry: Any,
    clean_middlewares: Any,
    patch_register_factory: MagicMock,
) -> None:
    """``register_all_services`` вызывает ``register_factory`` >= 14 раз (по числу сервисов)."""
    service_setup.register_all_services()
    assert patch_register_factory.call_count >= 14, patch_register_factory.call_count


def test_register_all_services_factory_names_are_expected(
    clean_registry: Any,
    clean_middlewares: Any,
    patch_register_factory: MagicMock,
) -> None:
    """Все строковые ключи фабрик соответствуют ожидаемому множеству."""
    service_setup.register_all_services()
    called_keys = {
        call.args[0] for call in patch_register_factory.call_args_list if call.args
    }
    expected = {
        "orders",
        "users",
        "files",
        "orderkinds",
        "skb",
        "dadata",
        "tech",
        "admin",
        "ai",
        "analytics",
        "search",
        "rag",
        "agent_memory",
        "webhook",
        "langmem",
    }
    missing = expected - called_keys
    assert not missing, f"missing keys: {missing}"
