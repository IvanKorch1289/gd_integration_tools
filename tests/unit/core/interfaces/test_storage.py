"""Unit tests for src.backend.core.interfaces.storage."""

from __future__ import annotations

import pytest

from src.backend.core.interfaces.storage import ObjectStorage


class TestObjectStorage:
    def test_cannot_instantiate(self) -> None:
        with pytest.raises(TypeError):
            ObjectStorage()  # type: ignore[abstract]

    def test_partial_subclass_fails(self) -> None:
        class Partial(ObjectStorage):
            async def upload(
                self, key: str, data: bytes, content_type: str | None = None
            ) -> str:
                return ""

        with pytest.raises(TypeError):
            Partial()  # type: ignore[abstract]

    def test_valid_subclass(self) -> None:
        class Full(ObjectStorage):
            async def upload(
                self, key: str, data: bytes, content_type: str | None = None
            ) -> str:
                return ""

            async def download(self, key: str) -> bytes:
                return b""

            async def delete(self, key: str) -> None:
                pass

            async def exists(self, key: str) -> bool:
                return False

            async def list_keys(self, prefix: str = "") -> list[str]:
                return []

            async def presigned_url(self, key: str, expires_in: int = 3600) -> str:
                return ""

        inst = Full()
        assert inst.supports_presigned() is True

    def test_supports_presigned_override(self) -> None:
        class NoPresign(ObjectStorage):
            async def upload(
                self, key: str, data: bytes, content_type: str | None = None
            ) -> str:
                return ""

            async def download(self, key: str) -> bytes:
                return b""

            async def delete(self, key: str) -> None:
                pass

            async def exists(self, key: str) -> bool:
                return False

            async def list_keys(self, prefix: str = "") -> list[str]:
                return []

            async def presigned_url(self, key: str, expires_in: int = 3600) -> str:
                return ""

            def supports_presigned(self) -> bool:
                return False

        assert NoPresign().supports_presigned() is False
