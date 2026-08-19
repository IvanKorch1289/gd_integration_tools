"""S193 W3: GZip compression middleware с path exclusion.

D-AUDIT-17601 fix (cycle 176): FastAPI's default GZipMiddleware
(BaseHTTPMiddleware pattern) incompatible с проектом's pure
ASGI middleware chain. На /docs, /redoc, /metrics → 500
'Internal server error' (start message suppressed, body dropped
or not re-sent).

Fix: pure ASGI GZipMiddleware с path exclusion. Paths /docs,
/docs/*, /redoc, /redoc/*, /metrics пропускаются через
compression (downstream handlers pass through unchanged).
"""

from __future__ import annotations

import gzip
import io

from starlette.types import ASGIApp, Message, Receive, Scope, Send

# Paths that are KNOWN to break with compression (cycle 175 root
# cause: GZipMiddleware BaseHTTPMiddleware incompatibility with
# data_masking, response_cache, etc.). For these, compression is
# skipped — downstream handlers pass through unchanged.
EXCLUDED_PATH_PREFIXES: tuple[str, ...] = ("/docs", "/redoc", "/metrics")


class GZipCompressionExcludingMiddleware:
    """Pure ASGI GZip middleware с path exclusion.

    Отличия от FastAPI's default:
    1. Path exclusion (список prefix'ов) — compression skipped для
       проблемных endpoints.
    2. Pure ASGI pattern (не BaseHTTPMiddleware) — pass start
       through, modify body on the fly (streaming).
    3. No double-buffering (compatible с project's ASGI chain).
    """

    def __init__(
        self,
        app: ASGIApp,
        minimum_size: int = 500,
        compresslevel: int = 9,
        excluded_prefixes: tuple[str, ...] = EXCLUDED_PATH_PREFIXES,
    ) -> None:
        self.app = app
        self.minimum_size = minimum_size
        self.compresslevel = compresslevel
        self.excluded_prefixes = excluded_prefixes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        # D-AUDIT-17601 fix: skip compression для known-broken paths.
        path: str = scope.get("path", "")
        if any(path == p or path.startswith(p + "/") for p in self.excluded_prefixes):
            # Pass through to downstream без compression.
            await self.app(scope, receive, send)
            return

        # Check Accept-Encoding: skip if client не поддерживает gzip.
        accept_encoding = ""
        for name, value in scope.get("headers", []):
            if name == b"accept-encoding":
                accept_encoding = value.decode("latin-1", errors="replace").lower()
                break
        if "gzip" not in accept_encoding:
            await self.app(scope, receive, send)
            return

        # Compress response.
        await self._compress(scope, receive, send)

    async def _compress(self, scope: Scope, receive: Receive, send: Send) -> None:
        """Compress the response body и re-send with Content-Encoding header."""
        started = False
        body_buffer = io.BytesIO()
        original_start: Message = {}

        async def send_with_compression(message: Message) -> None:
            nonlocal started, body_buffer, original_start
            if message["type"] == "http.response.start":
                # Buffer start, wait for body.
                original_start = message
            elif message["type"] == "http.response.body":
                if not started:
                    body_buffer.write(message.get("body", b""))
                    if not message.get("more_body", False):
                        # Last body chunk — compress и send.
                        body_data = body_buffer.getvalue()
                        if len(body_data) >= self.minimum_size:
                            compressed = gzip.compress(
                                body_data, compresslevel=self.compresslevel
                            )
                            # Update headers: Content-Encoding, Content-Length.
                            from starlette.datastructures import MutableHeaders

                            headers = MutableHeaders(
                                raw=original_start.get("headers", [])
                            )
                            headers["Content-Encoding"] = "gzip"
                            headers["Content-Length"] = str(len(compressed))
                            headers.add_vary_header("Accept-Encoding")
                            new_start = dict(original_start)
                            new_start["headers"] = list(headers.items())
                            await send(new_start)
                            await send(
                                {
                                    "type": "http.response.body",
                                    "body": compressed,
                                    "more_body": False,
                                }
                            )
                        else:
                            # Body too small — send uncompressed.
                            await send(original_start)
                            await send(message)
                        started = True
                else:
                    # Already sent compressed — shouldn't happen
                    # (all body buffered before compression).
                    await send(message)
            else:
                # Other message types — pass through.
                await send(message)

        await self.app(scope, receive, send_with_compression)
