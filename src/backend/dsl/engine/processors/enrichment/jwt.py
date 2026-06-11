from __future__ import annotations

"""S61 W2 — jwt.py part of enrichment decomp.

Classes: JwtSignProcessor, JwtVerifyProcessor.

JWT sign + verify.
"""

import time
from typing import Any

from src.backend.dsl.engine.context import ExecutionContext
from src.backend.dsl.engine.exchange import Exchange
from src.backend.dsl.engine.processors.base import BaseProcessor


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
        """Обработать exchange согласно логике процессора. Читает body / properties, мутирует exchange, raises exceptions для error handling pipeline."""
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
        """Сериализовать конфигурацию процессора в dict (для YAML/JSON spec). Returns None для non-serializable state."""
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
        """Обработать exchange согласно логике процессора. Читает body / properties, мутирует exchange, raises exceptions для error handling pipeline."""
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
        """Сериализовать конфигурацию процессора в dict (для YAML/JSON spec). Returns None для non-serializable state."""
        spec: dict[str, Any] = {"secret_key": self._secret}
        if self._algo != "HS256":
            spec["algorithm"] = self._algo
        if self._header != "Authorization":
            spec["header"] = self._header
        if self._output != "jwt_claims":
            spec["output_property"] = self._output
        return {"jwt_verify": spec}
