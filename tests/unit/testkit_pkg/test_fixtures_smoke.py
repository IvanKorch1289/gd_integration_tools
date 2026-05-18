"""Smoke: фикстуры testkit импортируются без ошибок.

Не поднимает контейнеры — проверяет только, что модули загружаются и
содержат ожидаемые атрибуты. Реальные docker-фикстуры покрыты в
chaos/integration suite'ах.
"""

from __future__ import annotations


def test_fixture_modules_importable() -> None:
    """Все fixture-модули импортируются и экспортируют ожидаемые символы."""
    from testkit.fixtures import db, redis, temporal, tenant, toxiproxy  # noqa: PLC0415

    assert hasattr(db, "postgres_url")
    assert hasattr(redis, "redis_url")
    assert hasattr(toxiproxy, "Toxiproxy")
    assert hasattr(toxiproxy, "toxiproxy")
    assert hasattr(temporal, "temporal_env")
    assert hasattr(tenant, "tenant_context")


def test_pytest_plugin_lists_fixtures() -> None:
    """pytest_plugins содержит все ожидаемые fixture-модули."""
    from testkit import pytest_plugin  # noqa: PLC0415

    plugins = set(pytest_plugin.pytest_plugins)
    assert {
        "testkit.fixtures.db",
        "testkit.fixtures.redis",
        "testkit.fixtures.toxiproxy",
        "testkit.fixtures.temporal",
        "testkit.fixtures.tenant",
    } <= plugins


def test_top_level_exports() -> None:
    """testkit.__init__ переэкспортирует основные символы."""
    import testkit  # noqa: PLC0415

    for name in (
        "HARCassette",
        "HARRecorder",
        "RouteRunResult",
        "RouteRunner",
        "build_replay_transport",
        "load_cassette",
        "record_session",
    ):
        assert hasattr(testkit, name), name
