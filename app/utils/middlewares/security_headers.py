from starlette.middleware.base import BaseHTTPMiddleware


__all__ = ("SecurityHeadersMiddleware",)


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Middleware for adding security headers to responses"""

    async def dispatch(self, request, call_next):
        response = await call_next(request)
        response.headers.update(
            {
                "Strict-Transport-Security": "max-age=63072000; includeSubDomains",
                "X-Content-Type-Options": "nosniff",
                "X-Frame-Options": "DENY",
                "Content-Security-Policy": "default-src 'self'",
                "Permissions-Policy": "geolocation=(), microphone=()",
            }
        )
        return response
