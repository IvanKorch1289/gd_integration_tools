"""Unit tests for src.backend.core.interfaces.secrets."""

from __future__ import annotations

import pytest

from src.backend.core.interfaces.secrets import SecretsBackend


class TestSecretsBackend:
    def test_cannot_instantiate(self) -> None:
        with pytest.raises(TypeError):
            SecretsBackend()  # type: ignore[abstract]

    def test_partial_subclass_fails(self) -> None:
        class Partial(SecretsBackend):
            async def get_secret(self, key: str) -> str | None:
                return None

        with pytest.raises(TypeError):
            Partial()  # type: ignore[abstract]

    def test_valid_subclass(self) -> None:
        class Full(SecretsBackend):
            async def get_secret(self, key: str) -> str | None:
                return None

            async def set_secret(self, key: str, value: str) -> None:
                pass

            async def delete_secret(self, key: str) -> bool:
                return False

            async def list_keys(self, prefix: str | None = None) -> list[str]:
                return []

        assert Full() is not None
