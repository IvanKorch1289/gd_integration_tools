"""ADR-0400: интроспекция GraphQL — конфиг-ключ + окружение.

Дефект: ``graphql_guards._introspection_allowed()`` смотрел только на
``settings.app.environment`` — декларативный ключ
``graphql.enable_introspection`` (base/prod/staging.yml) не учитывался,
т.е. конфиг-ключ был «не подключён».

Правило после фикса: интроспекция разрешена ТОЛЬКО если
``graphql.enable_introspection == true`` И ``app.environment ==
"development"``.
"""

from __future__ import annotations

import pytest

from src.backend.entrypoints.graphql import graphql_guards


@pytest.fixture
def env_and_flag(monkeypatch: pytest.MonkeyPatch) -> "pytest.MonkeyPatch":
    """Хелпер: выставить окружение и конфиг-флаг интроспекции."""
    from src.backend.core.config.services.graphql import graphql_settings
    from src.backend.core.config.settings import settings

    def _set(environment: str, *, enable_introspection: bool) -> None:
        monkeypatch.setattr(settings.app, "environment", environment)
        monkeypatch.setattr(
            graphql_settings, "enable_introspection", enable_introspection
        )

    _set("development", enable_introspection=True)
    return monkeypatch


@pytest.mark.unit
def test_introspection_allowed_in_development_with_flag(env_and_flag: object) -> None:
    """development + enable_introspection=true → интроспекция разрешена."""
    assert graphql_guards._introspection_allowed() is True


@pytest.mark.unit
def test_introspection_denied_when_flag_disabled(
    env_and_flag: pytest.MonkeyPatch,
) -> None:
    """development, но enable_introspection=false → интроспекция запрещена."""
    from src.backend.core.config.services.graphql import graphql_settings
    from src.backend.core.config.settings import settings

    env_and_flag.setattr(settings.app, "environment", "development")
    env_and_flag.setattr(graphql_settings, "enable_introspection", False)

    assert graphql_guards._introspection_allowed() is False


@pytest.mark.unit
def test_introspection_denied_outside_development(
    env_and_flag: pytest.MonkeyPatch,
) -> None:
    """staging/production + enable_introspection=true → всё равно запрещена."""
    from src.backend.core.config.services.graphql import graphql_settings
    from src.backend.core.config.settings import settings

    for environment in ("staging", "production"):
        env_and_flag.setattr(settings.app, "environment", environment)
        env_and_flag.setattr(graphql_settings, "enable_introspection", True)
        assert graphql_guards._introspection_allowed() is False


@pytest.mark.unit
def test_no_introspection_rule_added_when_flag_disabled(
    env_and_flag: pytest.MonkeyPatch,
) -> None:
    """При выключенном флаге в extensions появляется NoIntrospectionRule."""
    from src.backend.core.config.services.graphql import graphql_settings
    from src.backend.core.config.settings import settings

    env_and_flag.setattr(settings.app, "environment", "development")
    env_and_flag.setattr(graphql_settings, "enable_introspection", False)

    graphql_guards.reset_extensions_cache()
    try:
        extensions = graphql_guards.build_graphql_extensions()
    finally:
        graphql_guards.reset_extensions_cache()

    rules = [
        rule
        for extension in extensions
        for rule in getattr(extension, "validation_rules", [])
    ]
    assert any(rule is graphql_guards.NoIntrospectionRule for rule in rules), (
        "NoIntrospectionRule обязан добавляться при выключенной интроспекции"
    )


@pytest.mark.unit
def test_no_introspection_rule_absent_in_development(
    env_and_flag: pytest.MonkeyPatch,
) -> None:
    """В development с включённым флагом правило не добавляется."""
    graphql_guards.reset_extensions_cache()
    try:
        extensions = graphql_guards.build_graphql_extensions()
    finally:
        graphql_guards.reset_extensions_cache()

    rules = [
        rule
        for extension in extensions
        for rule in getattr(extension, "validation_rules", [])
    ]
    assert not any(rule is graphql_guards.NoIntrospectionRule for rule in rules)
