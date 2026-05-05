"""Enrichment processors — GeoIP, JWT, Compression, Deadline.

Все процессоры с graceful fallback при отсутствии библиотек.
"""

from __future__ import annotations

import logging
import time
from typing import Any

from src.backend.dsl.engine.context import ExecutionContext
from src.backend.dsl.engine.exchange import Exchange
from src.backend.dsl.engine.processors.base import BaseProcessor

__all__ = (
    "GeoIpProcessor",
    "JwtSignProcessor",
    "JwtVerifyProcessor",
    "CompressProcessor",
    "DecompressProcessor",
    "WebhookSignProcessor",
    "DeadlineProcessor",
)

logger = logging.getLogger("dsl.enrichment")


class GeoIpProcessor(BaseProcessor):
    """GeoIP enrichment via MaxMind GeoLite2.

    Reads IP from header/body field, looks up country/city/ISP,
    stores in exchange property.

    Requires: geoip2 library + GeoLite2-City.mmdb file at path given in ENV
    GEOIP_DB_PATH (default: /data/geoip/GeoLite2-City.mmdb).

    Usage::
        .geoip(ip_field="client_ip", output_property="geo")
    """

    def __init__(
        self,
        *,
        ip_field: str = "client_ip",
        ip_header: str | None = None,
        output_property: str = "geo",
        name: str | None = None,
    ) -> None:
        super().__init__(name=name or f"geoip:{ip_field}")
        self._ip_field = ip_field
        self._ip_header = ip_header
        self._output = output_property
        self._reader: Any = None

    def _get_reader(self) -> Any:
        if self._reader is None:
            import os

            try:
                import geoip2.database

                path = os.environ.get("GEOIP_DB_PATH", "/data/geoip/GeoLite2-City.mmdb")
                self._reader = geoip2.database.Reader(path)
            except (ImportError, FileNotFoundError, OSError) as exc:
                logger.debug("GeoIP reader unavailable: %s", exc)
                self._reader = False
        return self._reader

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        ip = None
        if self._ip_header:
            ip = exchange.in_message.headers.get(self._ip_header)
        if not ip:
            body = exchange.in_message.body
            if isinstance(body, dict):
                ip = body.get(self._ip_field)

        if not ip:
            exchange.set_property(self._output, None)
            return

        reader = self._get_reader()
        if not reader:
            exchange.set_property(
                self._output, {"ip": ip, "error": "geoip_unavailable"}
            )
            return

        try:
            record = reader.city(ip)
            exchange.set_property(
                self._output,
                {
                    "ip": ip,
                    "country": record.country.iso_code,
                    "country_name": record.country.name,
                    "city": record.city.name,
                    "latitude": float(record.location.latitude)
                    if record.location.latitude
                    else None,
                    "longitude": float(record.location.longitude)
                    if record.location.longitude
                    else None,
                    "timezone": record.location.time_zone,
                },
            )
        except Exception as exc:
            exchange.set_property(self._output, {"ip": ip, "error": str(exc)})

    def to_spec(self) -> dict[str, Any] | None:
        spec: dict[str, Any] = {}
        if self._ip_field != "client_ip":
            spec["ip_field"] = self._ip_field
        if self._ip_header is not None:
            spec["ip_header"] = self._ip_header
        if self._output != "geo":
            spec["output_property"] = self._output
        return {"geoip": spec}


class JwtSignProcessor(BaseProcessor):
    """Sign payload as JWT with secret + algorithm.

    Usage::
        .jwt_sign(secret_key="SECRET_KEY", algorithm="HS256", output_property="token")
    """

    def __init__(
        self,
        *,
        secret_key: str,
        algorithm: str = "HS256",
        expires_in_seconds: int | None = 3600,
        output_property: str = "jwt",
        name: str | None = None,
    ) -> None:
        super().__init__(name=name or f"jwt_sign:{algorithm}")
        self._secret = secret_key
        self._algo = algorithm
        self._exp = expires_in_seconds
        self._output = output_property

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        try:
            import jwt
        except ImportError:
            exchange.fail("PyJWT not installed")
            return

        body = exchange.in_message.body
        payload = dict(body) if isinstance(body, dict) else {"sub": str(body)}

        if self._exp:
            payload["exp"] = int(time.time()) + self._exp
            payload["iat"] = int(time.time())

        try:
            token = jwt.encode(payload, self._secret, algorithm=self._algo)
            if isinstance(token, bytes):
                token = token.decode("utf-8")
            exchange.set_property(self._output, token)
        except Exception as exc:
            exchange.fail(f"JWT sign failed: {exc}")

    def to_spec(self) -> dict[str, Any] | None:
        spec: dict[str, Any] = {"secret_key": self._secret}
        if self._algo != "HS256":
            spec["algorithm"] = self._algo
        if self._exp != 3600:
            spec["expires_in_seconds"] = self._exp
        if self._output != "jwt":
            spec["output_property"] = self._output
        return {"jwt_sign": spec}


class JwtVerifyProcessor(BaseProcessor):
    """Verify JWT from header. Stores claims в property или fail.

    Usage::
        .jwt_verify(secret_key="...", algorithm="HS256", header="Authorization")
    """

    def __init__(
        self,
        *,
        secret_key: str,
        algorithm: str = "HS256",
        header: str = "Authorization",
        output_property: str = "jwt_claims",
        name: str | None = None,
    ) -> None:
        super().__init__(name=name or "jwt_verify")
        self._secret = secret_key
        self._algo = algorithm
        self._header = header
        self._output = output_property

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        try:
            import jwt
        except ImportError:
            exchange.fail("PyJWT not installed")
            return

        raw = exchange.in_message.headers.get(self._header, "")
        if raw.startswith("Bearer "):
            raw = raw[7:]
        if not raw:
            exchange.fail(f"Missing JWT in header '{self._header}'")
            return

        try:
            claims = jwt.decode(raw, self._secret, algorithms=[self._algo])
            exchange.set_property(self._output, claims)
        except jwt.ExpiredSignatureError:
            exchange.fail("JWT expired")
        except jwt.InvalidTokenError as exc:
            exchange.fail(f"Invalid JWT: {exc}")

    def to_spec(self) -> dict[str, Any] | None:
        spec: dict[str, Any] = {"secret_key": self._secret}
        if self._algo != "HS256":
            spec["algorithm"] = self._algo
        if self._header != "Authorization":
            spec["header"] = self._header
        if self._output != "jwt_claims":
            spec["output_property"] = self._output
        return {"jwt_verify": spec}


class CompressProcessor(BaseProcessor):
    """Compress body через gzip/brotli/zstd.

    Usage::
        .compress(algorithm="gzip")
    """

    def __init__(
        self, *, algorithm: str = "gzip", level: int = 6, name: str | None = None
    ) -> None:
        super().__init__(name=name or f"compress:{algorithm}")
        self._algo = algorithm
        self._level = level

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        import orjson

        body = exchange.in_message.body
        if isinstance(body, str):
            data = body.encode("utf-8")
        elif isinstance(body, bytes):
            data = body
        else:
            data = orjson.dumps(body, default=str)

        try:
            if self._algo == "gzip":
                import gzip

                compressed = gzip.compress(data, compresslevel=self._level)
            elif self._algo == "brotli":
                import brotli

                compressed = brotli.compress(data, quality=self._level)
            elif self._algo == "zstd":
                import zstandard

                cctx = zstandard.ZstdCompressor(level=self._level)
                compressed = cctx.compress(data)
            else:
                exchange.fail(f"Unknown compression algorithm: {self._algo}")
                return

            exchange.set_property("compress_original_size", len(data))
            exchange.set_property(
                "compress_ratio", round(len(compressed) / max(len(data), 1), 3)
            )
            exchange.set_out(body=compressed, headers=dict(exchange.in_message.headers))
        except ImportError as exc:
            exchange.fail(f"Compression library missing: {exc}")

    def to_spec(self) -> dict[str, Any] | None:
        spec: dict[str, Any] = {}
        if self._algo != "gzip":
            spec["algorithm"] = self._algo
        if self._level != 6:
            spec["level"] = self._level
        return {"compress": spec}


class DecompressProcessor(BaseProcessor):
    """Decompress body (auto-detect или указанный algorithm)."""

    def __init__(self, *, algorithm: str = "auto", name: str | None = None) -> None:
        super().__init__(name=name or f"decompress:{algorithm}")
        self._algo = algorithm

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        body = exchange.in_message.body
        if not isinstance(body, bytes):
            exchange.fail("DecompressProcessor requires bytes body")
            return

        algo = self._algo
        if algo == "auto":
            if body[:2] == b"\x1f\x8b":
                algo = "gzip"
            elif body[:4] == b"\x28\xb5\x2f\xfd":
                algo = "zstd"
            else:
                algo = "brotli"

        try:
            if algo == "gzip":
                import gzip

                data = gzip.decompress(body)
            elif algo == "brotli":
                import brotli

                data = brotli.decompress(body)
            elif algo == "zstd":
                import zstandard

                dctx = zstandard.ZstdDecompressor()
                data = dctx.decompress(body)
            else:
                exchange.fail(f"Unknown algorithm: {algo}")
                return
            exchange.set_out(body=data, headers=dict(exchange.in_message.headers))
        except ImportError as exc:
            exchange.fail(f"Decompression library missing: {exc}")
        except Exception as exc:
            exchange.fail(f"Decompress failed: {exc}")

    def to_spec(self) -> dict[str, Any] | None:
        spec: dict[str, Any] = {}
        if self._algo != "auto":
            spec["algorithm"] = self._algo
        return {"decompress": spec}


class WebhookSignProcessor(BaseProcessor):
    """Sign outgoing webhook body with HMAC-SHA256.

    Usage::
        .webhook_sign(secret="KEY", header="X-Webhook-Signature")
    """

    def __init__(
        self,
        *,
        secret: str,
        header: str = "X-Webhook-Signature",
        algorithm: str = "sha256",
        name: str | None = None,
    ) -> None:
        super().__init__(name=name or f"webhook_sign:{algorithm}")
        self._secret = secret
        self._header = header
        self._algo = algorithm

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        import hashlib
        import hmac

        import orjson

        body = exchange.in_message.body
        if isinstance(body, str):
            data = body.encode("utf-8")
        elif isinstance(body, bytes):
            data = body
        else:
            data = orjson.dumps(body, default=str)

        algo = getattr(hashlib, self._algo, None)
        if algo is None:
            exchange.fail(f"Unknown hash algorithm: {self._algo}")
            return

        signature = hmac.new(self._secret.encode(), data, algo).hexdigest()
        exchange.in_message.set_header(self._header, signature)
        exchange.set_property("webhook_signature", signature)

    def to_spec(self) -> dict[str, Any] | None:
        spec: dict[str, Any] = {"secret": self._secret}
        if self._header != "X-Webhook-Signature":
            spec["header"] = self._header
        if self._algo != "sha256":
            spec["algorithm"] = self._algo
        return {"webhook_sign": spec}


class DeadlineProcessor(BaseProcessor):
    """Устанавливает дedline для pipeline — проверяется последующими процессорами.

    Usage::
        .deadline(timeout_seconds=30)
        # ... дальнейшие процессоры проверяют exchange.properties['_deadline_at']
    """

    def __init__(
        self,
        *,
        timeout_seconds: float = 30.0,
        fail_on_exceed: bool = True,
        name: str | None = None,
    ) -> None:
        super().__init__(name=name or f"deadline({timeout_seconds}s)")
        self._timeout = timeout_seconds
        self._fail = fail_on_exceed

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        now = time.monotonic()

        existing = exchange.properties.get("_deadline_at")
        if existing is not None and isinstance(existing, (int, float)):
            if now >= existing:
                if self._fail:
                    exchange.fail(f"Deadline exceeded by {now - existing:.2f}s")
                return
            return

        exchange.set_property("_deadline_at", now + self._timeout)
        exchange.set_property("_deadline_set_at", now)

    def to_spec(self) -> dict[str, Any] | None:
        spec: dict[str, Any] = {}
        if self._timeout != 30.0:
            spec["timeout_seconds"] = self._timeout
        if self._fail is not True:
            spec["fail_on_exceed"] = self._fail
        return {"deadline": spec}
