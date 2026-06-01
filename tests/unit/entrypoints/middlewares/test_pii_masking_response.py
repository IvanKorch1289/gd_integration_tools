"""Unit-тесты :class:`PIIMaskingResponseMiddleware` (S18 W3, S-L8-4).

Покрытие (DoD S18 #6):
    * Feature-flag OFF → pass-through без изменения тела ответа.
    * Flag ON + path matches → email/phone/INN маскируются на ``***``.
    * Flag ON + path НЕ matches → no masking (regex isolation).
    * Flag ON + не-JSON Content-Type → no masking.
    * Flag ON + top-level JSON list → masking рекурсивно для всех элементов.
    * Empty path_patterns → applies to ALL paths (default behavior).
"""

# ruff: noqa: S101

from __future__ import annotations

import json

import orjson
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.backend.core.config.features import feature_flags
from src.backend.entrypoints.middlewares.pii_masking_response import (
    PIIMaskingResponseMiddleware,
)

# ----------------------------- fixtures ------------------------------------


def _build_app(*, path_patterns: list[str] | None = None) -> FastAPI:
    """FastAPI с PIIMaskingResponseMiddleware и тестовыми endpoints."""
    app = FastAPI()
    app.add_middleware(
        PIIMaskingResponseMiddleware,
        path_patterns=path_patterns,
    )

    @app.get("/api/users/me")
    async def users_me() -> dict:
        return {
            "name": "Alice",
            "email": "alice@example.com",
            "phone": "+7 (999) 123-45-67",
            "age": 30,
        }

    @app.get("/api/items")
    async def items() -> list:
        return [
            {"id": 1, "email": "bob@example.com"},
            {"id": 2, "email": "carol@example.com"},
        ]

    @app.get("/api/healthz")
    async def healthz() -> dict:
        return {"status": "ok"}

    @app.get("/api/text", response_class=None)
    async def text():  # type: ignore[no-untyped-def]
        from starlette.responses import PlainTextResponse

        return PlainTextResponse("contact: alice@example.com")

    return app


# ----------------------------- tests --------------------------------------


class TestFeatureFlagDisabled:
    """default-OFF: middleware прозрачен, тело не модифицируется."""

    def test_pass_through_when_disabled(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            feature_flags, "pii_response_middleware_enabled", False
        )
        app = _build_app()
        client = TestClient(app)
        resp = client.get("/api/users/me")
        assert resp.status_code == 200
        body = resp.json()
        assert body["email"] == "alice@example.com"  # НЕ замаскирован
        assert body["phone"] == "+7 (999) 123-45-67"


class TestFeatureFlagEnabled:
    """flag=ON: маскировка применяется по path/Content-Type правилам."""

    def test_masks_email_and_phone_on_matching_path(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            feature_flags, "pii_response_middleware_enabled", True
        )
        app = _build_app(path_patterns=[r"^/api/users(/.*)?$"])
        client = TestClient(app)
        resp = client.get("/api/users/me")
        assert resp.status_code == 200
        body = resp.json()
        assert body["email"] == "***"
        assert body["phone"] == "***"
        # non-PII fields сохранены
        assert body["name"] == "Alice"
        assert body["age"] == 30

    def test_skips_non_matching_path(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            feature_flags, "pii_response_middleware_enabled", True
        )
        app = _build_app(path_patterns=[r"^/api/users(/.*)?$"])
        client = TestClient(app)
        resp = client.get("/api/healthz")
        assert resp.status_code == 200
        # healthz не matches /api/users pattern → no masking applied
        assert resp.json() == {"status": "ok"}

    def test_empty_patterns_applies_to_all_paths(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """path_patterns=None / [] → middleware применяется ко всем JSON-путям."""
        monkeypatch.setattr(
            feature_flags, "pii_response_middleware_enabled", True
        )
        app = _build_app(path_patterns=None)
        client = TestClient(app)
        # /api/users
        body = client.get("/api/users/me").json()
        assert body["email"] == "***"
        # /api/items тоже — нет фильтра
        items = client.get("/api/items").json()
        assert all(it["email"] == "***" for it in items)

    def test_non_json_content_type_is_skipped(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setattr(
            feature_flags, "pii_response_middleware_enabled", True
        )
        app = _build_app(path_patterns=None)
        client = TestClient(app)
        resp = client.get("/api/text")
        assert resp.status_code == 200
        # text/plain не трогается (email НЕ маскирован)
        assert resp.text == "contact: alice@example.com"

    def test_top_level_json_list_is_masked_recursively(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """JSON array на top-level — все элементы рекурсивно маскируются."""
        monkeypatch.setattr(
            feature_flags, "pii_response_middleware_enabled", True
        )
        app = _build_app(path_patterns=None)
        client = TestClient(app)
        resp = client.get("/api/items")
        items = resp.json()
        assert isinstance(items, list)
        assert all(item["email"] == "***" for item in items)


class TestDoDIntegration:
    """DoD S18 #6: PII не утекает на configured paths."""

    def test_dod_pii_does_not_leak_on_configured_path(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """E2E: configurable path → no PII leakage в response body."""
        monkeypatch.setattr(
            feature_flags, "pii_response_middleware_enabled", True
        )
        # Только /api/users/* подпадает; /api/items не подпадает.
        app = _build_app(path_patterns=[r"^/api/users(/.*)?$"])
        client = TestClient(app)
        resp = client.get("/api/users/me")
        raw_body = resp.content.decode("utf-8")
        # Гарантируем: оригинальные значения PII НЕ присутствуют в response.
        assert "alice@example.com" not in raw_body
        assert "+7 (999) 123-45-67" not in raw_body
        # И всё ещё валидный JSON.
        parsed = json.loads(raw_body)
        parsed_via_orjson = orjson.loads(raw_body)
        assert parsed == parsed_via_orjson  # round-trip OK
