"""Pure ASGI regression-тесты для AdminAuditMiddleware (cycle 49)."""


from __future__ import annotations

import logging
from unittest.mock import AsyncMock

import pytest

from src.backend.entrypoints.middlewares.admin_audit import AdminAuditMiddleware


def _start_message(send: AsyncMock):
    for call in send.await_args_list:
        msg = call.args[0]
        if msg["type"] == "http.response.start":
            return msg
    return None


def _downstream_ok(status_code: int = 200):
    async def downstream(scope, receive, send):
        # Consume body for re-injection invariant.
        more_body = True
        while more_body:
            msg = await receive()
            if msg["type"] == "http.disconnect":
                break
            more_body = msg.get("more_body", False)
        await send(
            {"type": "http.response.start", "status": status_code, "headers": []}
        )
        await send({"type": "http.response.body", "body": b"ok"})

    return downstream


def _make_scope(
    method: str = "PATCH",
    path: str = "/tech/degradation/level",
    state: dict | None = None,
    headers: list[tuple[bytes, bytes]] | None = None,
) -> dict:
    return {
        "type": "http",
        "method": method,
        "url": f"http://test{path}",
        "path": path,
        "headers": headers or [],
        "query_string": b"",
        "client": ("127.0.0.1", 1234),
        **({"state": state} if state is not None else {}),
    }


def _make_receive(body: bytes = b""):
    async def receive():
        return {"type": "http.request", "body": body, "more_body": False}
    return receive


class TestAdminAuditMiddlewarePureASGI:
    """Cycle 49: pure ASGI regression-тесты для AdminAuditMiddleware."""

    @pytest.mark.asyncio
    async def test_passes_through_non_http_scope(self, caplog: pytest.LogCaptureFixture) -> None:
        """Non-HTTP scope (websocket) пробрасывается без audit."""
        caplog.set_level(logging.INFO, logger="audit_log.admin")
        app = AsyncMock()

        async def downstream(scope, receive, send):
            await send({"type": "websocket.accept"})

        app.side_effect = downstream
        mw = AdminAuditMiddleware(app=app)

        send = AsyncMock()
        await mw(
            {"type": "websocket", "path": "/tech/ws", "headers": []},
            AsyncMock(),
            send,
        )

        msgs = [c.args[0] for c in send.await_args_list]
        assert any(m["type"] == "websocket.accept" for m in msgs)

    @pytest.mark.asyncio
    async def test_get_method_skips_audit(self, caplog: pytest.LogCaptureFixture) -> None:
        """GET методы не аудитируются (только state-changing)."""
        caplog.set_level(logging.INFO, logger="audit_log.admin")
        app = AsyncMock()
        app.side_effect = _downstream_ok()
        mw = AdminAuditMiddleware(app=app)

        send = AsyncMock()
        await mw(
            _make_scope("GET", "/api/v1/admin/something"),
            _make_receive(),
            send,
        )

        records = [r for r in caplog.records if r.name == "audit_log.admin"]
        assert not records, "GET не должен попадать в admin-audit"

    @pytest.mark.asyncio
    async def test_non_admin_path_skips_audit(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Non-admin path (e.g. /api/v1/users) → не аудитируется даже для POST."""
        caplog.set_level(logging.INFO, logger="audit_log.admin")
        app = AsyncMock()
        app.side_effect = _downstream_ok()
        mw = AdminAuditMiddleware(app=app)

        send = AsyncMock()
        await mw(
            _make_scope("POST", "/api/v1/users"),
            _make_receive(b'{"x":1}'),
            send,
        )

        records = [r for r in caplog.records if r.name == "audit_log.admin"]
        assert not records

    @pytest.mark.asyncio
    async def test_put_admin_path_emits_audit(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """PUT /api/v1/admin/* → audit log emitted."""
        caplog.set_level(logging.INFO, logger="audit_log.admin")
        app = AsyncMock()
        app.side_effect = _downstream_ok()
        mw = AdminAuditMiddleware(app=app)

        from types import SimpleNamespace

        auth_ctx = SimpleNamespace(
            method=SimpleNamespace(value="JWT"),
            principal="admin-42",
            metadata={"admin_roles": ["super_admin"]},
        )

        send = AsyncMock()
        await mw(
            _make_scope(
                "PUT",
                "/api/v1/admin/users/1",
                state={"auth_context": auth_ctx},
            ),
            _make_receive(b'{"role":"operator"}'),
            send,
        )

        records = [r for r in caplog.records if r.name == "audit_log.admin"]
        assert records, "PUT /api/v1/admin/* должен emit audit"
        rec = records[0]
        assert rec.actor_principal == "admin-42"
        assert "super_admin" in rec.actor_admin_roles
        assert rec.endpoint == "/api/v1/admin/users/1"
        assert rec.method == "PUT"

    @pytest.mark.asyncio
    async def test_delete_admin_path_emits_audit(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """DELETE /api/v1/admin/* → audit log emitted."""
        caplog.set_level(logging.INFO, logger="audit_log.admin")
        app = AsyncMock()
        app.side_effect = _downstream_ok()
        mw = AdminAuditMiddleware(app=app)

        from types import SimpleNamespace

        auth_ctx = SimpleNamespace(
            method=SimpleNamespace(value="JWT"),
            principal="ops-1",
            metadata={},
        )

        send = AsyncMock()
        await mw(
            _make_scope(
                "DELETE",
                "/api/v1/admin/users/42",
                state={"auth_context": auth_ctx},
            ),
            _make_receive(),
            send,
        )

        records = [r for r in caplog.records if r.name == "audit_log.admin"]
        assert records
        assert records[0].method == "DELETE"

    @pytest.mark.asyncio
    async def test_tech_path_emits_audit(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Path /tech/* → admin audit (cycle 49 S13 K1 W2 spec)."""
        caplog.set_level(logging.INFO, logger="audit_log.admin")
        app = AsyncMock()
        app.side_effect = _downstream_ok()
        mw = AdminAuditMiddleware(app=app)

        from types import SimpleNamespace

        auth_ctx = SimpleNamespace(
            method=SimpleNamespace(value="JWT"),
            principal="ops-tech",
            metadata={"admin_roles": ["operator"]},
        )

        send = AsyncMock()
        await mw(
            _make_scope(
                "POST",
                "/tech/feature-flags/refresh",
                state={"auth_context": auth_ctx},
            ),
            _make_receive(),
            send,
        )

        records = [r for r in caplog.records if r.name == "audit_log.admin"]
        assert records
        assert records[0].endpoint == "/tech/feature-flags/refresh"

    @pytest.mark.asyncio
    async def test_anonymous_principal_when_no_auth_context(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Без auth_context в state → principal='anonymous', metadata={}."""
        caplog.set_level(logging.INFO, logger="audit_log.admin")
        app = AsyncMock()
        app.side_effect = _downstream_ok()
        mw = AdminAuditMiddleware(app=app)

        send = AsyncMock()
        await mw(
            _make_scope("POST", "/tech/admin-action", state={}),  # no auth_context
            _make_receive(),
            send,
        )

        records = [r for r in caplog.records if r.name == "audit_log.admin"]
        assert records
        assert records[0].actor_principal == "anonymous"
        assert records[0].actor_admin_roles == []

    @pytest.mark.asyncio
    async def test_response_status_captured(self, caplog: pytest.LogCaptureFixture) -> None:
        """Status code из downstream captured через send_wrapper (cycle 49)."""
        caplog.set_level(logging.INFO, logger="audit_log.admin")
        app = AsyncMock()
        app.side_effect = _downstream_ok(status_code=403)
        mw = AdminAuditMiddleware(app=app)

        from types import SimpleNamespace

        auth_ctx = SimpleNamespace(
            method=SimpleNamespace(value="JWT"),
            principal="ops",
            metadata={},
        )

        send = AsyncMock()
        await mw(
            _make_scope(
                "POST",
                "/api/v1/admin/forbidden",
                state={"auth_context": auth_ctx},
            ),
            _make_receive(),
            send,
        )

        records = [r for r in caplog.records if r.name == "audit_log.admin"]
        assert records
        assert records[0].status_code == 403

    @pytest.mark.asyncio
    async def test_payload_hash_computed_for_body(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """payload_hash = SHA256(body) prefix 16 chars (compliance)."""
        caplog.set_level(logging.INFO, logger="audit_log.admin")
        app = AsyncMock()
        app.side_effect = _downstream_ok()
        mw = AdminAuditMiddleware(app=app)

        from types import SimpleNamespace

        from src.backend.entrypoints.middlewares._body_hash import payload_hash

        auth_ctx = SimpleNamespace(
            method=SimpleNamespace(value="JWT"),
            principal="ops",
            metadata={},
        )

        body = b'{"action":"promote","target":"user-1"}'
        send = AsyncMock()
        await mw(
            _make_scope(
                "POST",
                "/api/v1/admin/users/1/promote",
                state={"auth_context": auth_ctx},
            ),
            _make_receive(body),
            send,
        )

        records = [r for r in caplog.records if r.name == "audit_log.admin"]
        assert records
        assert records[0].payload_hash == payload_hash(body)

    @pytest.mark.asyncio
    async def test_downstream_consumes_replayed_body(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Cycle 49 invariant: downstream прочитывает body через replay_receive."""
        caplog.set_level(logging.INFO, logger="audit_log.admin")
        captured_body = {}

        async def downstream(scope, receive, send):
            body_bytes = b""
            more_body = True
            while more_body:
                msg = await receive()
                if msg["type"] == "http.disconnect":
                    break
                body_bytes += msg.get("body", b"")
                more_body = msg.get("more_body", False)
            captured_body["body"] = body_bytes
            await send({"type": "http.response.start", "status": 200, "headers": []})
            await send({"type": "http.response.body", "body": b"ok"})

        app = AsyncMock()
        app.side_effect = downstream
        mw = AdminAuditMiddleware(app=app)

        from types import SimpleNamespace

        auth_ctx = SimpleNamespace(
            method=SimpleNamespace(value="JWT"),
            principal="ops",
            metadata={},
        )

        send = AsyncMock()
        await mw(
            _make_scope(
                "POST",
                "/api/v1/admin/test",
                state={"auth_context": auth_ctx},
            ),
            _make_receive(b"admin-payload"),
            send,
        )

        assert captured_body["body"] == b"admin-payload"

    @pytest.mark.asyncio
    async def test_uses_cached_body_when_available(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """IL-OBS1: state['body'] (cached от RequestBodyCache) имеет приоритет."""
        caplog.set_level(logging.INFO, logger="audit_log.admin")
        app = AsyncMock()
        app.side_effect = _downstream_ok()
        mw = AdminAuditMiddleware(app=app)

        from types import SimpleNamespace

        from src.backend.entrypoints.middlewares._body_hash import payload_hash

        auth_ctx = SimpleNamespace(
            method=SimpleNamespace(value="JWT"),
            principal="ops",
            metadata={},
        )

        send = AsyncMock()
        await mw(
            _make_scope(
                "POST",
                "/api/v1/admin/cached",
                state={"auth_context": auth_ctx, "body": b"cached-body"},
            ),
            _make_receive(b"ignored"),
            send,
        )

        records = [r for r in caplog.records if r.name == "audit_log.admin"]
        assert records
        # payload_hash из cached body, не из receive.
        assert records[0].payload_hash == payload_hash(b"cached-body")
