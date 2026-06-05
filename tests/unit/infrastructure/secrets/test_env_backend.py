"""Unit-тесты для ``src.backend.infrastructure.secrets.env_backend.EnvBackend``."""

# ruff: noqa: S101

from __future__ import annotations

import pytest

from src.backend.infrastructure.secrets.broker import SecretValue
from src.backend.infrastructure.secrets.env_backend import EnvBackend


@pytest.mark.unit
class TestEnvBackendEnvName:
    def test_env_name_without_prefix(self) -> None:
        backend = EnvBackend()
        assert backend._env_name("db/postgres") == "DB__POSTGRES"
        assert backend._env_name("my-secret") == "MY_SECRET"
        assert backend._env_name("a/b-c") == "A__B_C"

    def test_env_name_with_prefix(self, monkeypatch: pytest.MonkeyPatch) -> None:
        backend = EnvBackend(prefix="app__")
        assert backend._env_name("db/postgres") == "APP__DB__POSTGRES"


@pytest.mark.unit
class TestEnvBackendGet:
    def test_get_returns_secret_value_when_env_set(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("DB__POSTGRES", "pg-password")
        backend = EnvBackend()

        value = backend.get("db/postgres")

        assert value == SecretValue(name="db/postgres", value="pg-password", version=0)

    def test_get_raises_when_secret_missing(self) -> None:
        backend = EnvBackend()
        with pytest.raises(KeyError, match="db/missing"):
            backend.get("db/missing")


@pytest.mark.unit
class TestEnvBackendGetVersioned:
    def test_get_versioned_ignores_version_and_returns_current(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("API_KEY", "current-key")
        backend = EnvBackend()

        value = backend.get_versioned("api-key", version=99)

        assert value == SecretValue(name="api-key", value="current-key", version=0)
