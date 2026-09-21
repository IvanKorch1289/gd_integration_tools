"""Unit tests for src.backend.core.protocols."""

from __future__ import annotations

from src.backend.core.protocols import (
    BrowserAutomation,
    CDCStrategy,
    Exporter,
    LLMProvider,
    MemoryBackend,
    NotificationChannel,
    NotificationMessage,
    PromptStore,
    SoapClient,
)


class TestLLMProvider:
    def test_is_runtime_checkable(self) -> None:
        class Fake:
            name: str = "test"

            async def chat(
                self, messages: list[dict[str, object]], **kwargs: object
            ) -> dict[str, object]:
                return {}

            def extract_text(self, response: dict[str, object]) -> str:
                return ""

            async def embeddings(
                self, texts: list[str], **kwargs: object
            ) -> list[list[float]]:
                return []

        assert isinstance(Fake(), LLMProvider)

    def test_missing_method_fails(self) -> None:
        class Bad:
            name: str = "test"

        assert not isinstance(Bad(), LLMProvider)


class TestBrowserAutomation:
    def test_is_runtime_checkable(self) -> None:
        class Fake:
            async def navigate(self, url: str, *, wait_until: str = "load") -> None:
                pass

            async def click(self, selector: str, *, timeout_ms: int = 30_000) -> None:
                pass

            async def fill(self, selector: str, value: str) -> None:
                pass

            async def extract(self, selector: str) -> str:
                return ""

            async def screenshot(self, *, full_page: bool = False) -> bytes:
                return b""

            async def download(self, selector: str) -> bytes:
                return b""

        assert isinstance(Fake(), BrowserAutomation)


class TestNotificationChannel:
    def test_is_runtime_checkable(self) -> None:
        class Fake:
            channel_name: str = "email"

            async def send(self, message: NotificationMessage) -> bool:
                return True

            def supports_format(self, content_type: str) -> bool:
                return True

            async def health(self) -> bool:
                return True

        assert isinstance(Fake(), NotificationChannel)


class TestExporter:
    def test_is_runtime_checkable(self) -> None:
        class Fake:
            format_name: str = "csv"
            mime_type: str = "text/csv"

            def export(
                self, data: object, *, options: dict[str, object] | None = None
            ) -> bytes:
                return b""

            def get_extension(self) -> str:
                return "csv"

        assert isinstance(Fake(), Exporter)


class TestMemoryBackend:
    def test_is_runtime_checkable(self) -> None:
        class Fake:
            async def get_conversation(
                self, session_id: str, *, limit: int = 50
            ) -> list[dict[str, object]]:
                return []

            async def append_message(
                self, session_id: str, message: dict[str, object]
            ) -> None:
                pass

            async def save_long_term(
                self, user_id: str, facts: dict[str, object]
            ) -> None:
                pass

            async def get_facts(self, user_id: str) -> dict[str, object]:
                return {}

            async def clear(self, session_id: str) -> None:
                pass

        assert isinstance(Fake(), MemoryBackend)


class TestCDCStrategy:
    def test_is_runtime_checkable(self) -> None:
        class Fake:
            strategy_name: str = "poll"

            async def subscribe(self, tables: list[str]) -> None:
                pass

            def stream(self) -> object:
                return object()

            async def stop(self) -> None:
                pass

        assert isinstance(Fake(), CDCStrategy)


class TestSoapClient:
    def test_is_runtime_checkable(self) -> None:
        class Fake:
            async def call(self, method: str, **params: object) -> object:
                return object()

            def list_methods(self) -> list[str]:
                return []

        assert isinstance(Fake(), SoapClient)


class TestPromptStore:
    def test_is_runtime_checkable(self) -> None:
        class Fake:
            async def get(self, name: str, *, version: int | None = None) -> str:
                return ""

            async def register(
                self,
                name: str,
                content: str,
                *,
                metadata: dict[str, object] | None = None,
            ) -> int:
                return 1

            async def list_versions(self, name: str) -> list[int]:
                return []

        assert isinstance(Fake(), PromptStore)
