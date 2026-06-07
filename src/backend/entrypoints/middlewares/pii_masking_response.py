"""PII masking response middleware (S18 W3, S-L8-4).

Глобальный wrapper, применяющий :class:`core.security.pii_masker.PIIMasker`
к JSON-телам ответов на configurable path patterns. В отличие от
:class:`entrypoints.middlewares.data_masking.DataMaskingMiddleware` (S8A
legacy, локальные regex), этот middleware использует единый
:func:`default_masker` из ``core.security.pii_masker``, что соответствует
плану S22 W1 A-07 «PII Masker Unification» (см. KNOWN_ISSUES.md).

Поведение:
    * Feature-flag ``pii_response_middleware_enabled`` (default-OFF) —
      при False middleware прозрачен (pass-through call_next).
    * ``path_patterns`` (список regex) ограничивает применение к
      указанным путям. ``None`` или ``[]`` → применять ко всем путям.
    * Применяется только к ответам с ``Content-Type: application/json``.
    * Используется :meth:`PIIMasker.mask_dict` (rekursive); 8 типов PII
      покрыты дефолтными patterns (jwt/iban/snils/card/passport/email/inn/phone).

Пример::

    from fastapi import FastAPI
    from src.backend.entrypoints.middlewares.pii_masking_response import (
        PIIMaskingResponseMiddleware,
    )

    app = FastAPI()
    app.add_middleware(
        PIIMaskingResponseMiddleware,
        path_patterns=[r"^/api/v1/users(/.*)?$", r"^/api/v1/admin/.*$"],
    )
"""

from __future__ import annotations
from src.backend.infrastructure.logging.factory import get_logger


import re
from collections.abc import Iterable
from typing import Any

from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.types import ASGIApp

from src.backend.core.security.pii_masker import default_masker
from src.backend.core.utils.async_helpers import AsyncChunkIterator

__all__ = ("PIIMaskingResponseMiddleware",)

_logger = get_logger(__name__)


class PIIMaskingResponseMiddleware(BaseHTTPMiddleware):
    """Маскирует PII в JSON-телах ответов на configurable путях.

    Args:
        app: ASGI-приложение.
        path_patterns: Список regex для путей, к которым применять
            маскировку. ``None`` / пустой список — применять ко всем
            путям. Сравнение через :func:`re.search` (match anywhere
            в pathname). Шаблоны компилируются в ``__init__``.

    Notes:
        Feature-flag ``pii_response_middleware_enabled`` (S18 W3
        backbone) проверяется внутри :meth:`dispatch` lazy-импортом
        — middleware можно безопасно зарегистрировать даже когда flag
        выключен. При OFF behavior идентичен pass-through.
    """

    def __init__(
        self, app: ASGIApp, *, path_patterns: Iterable[str] | None = None
    ) -> None:
        super().__init__(app)
        self._path_patterns: tuple[re.Pattern[str], ...] = tuple(
            re.compile(p) for p in (path_patterns or ())
        )

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        if not self._is_enabled():
            return await call_next(request)

        if not self._path_matches(request.url.path):
            return await call_next(request)

        response = await call_next(request)

        content_type = response.headers.get("content-type", "")
        if "application/json" not in content_type:
            return response

        body = await self._capture_body(response)
        try:
            masked = self._mask_json_bytes(body)
        except Exception as exc:
            _logger.warning(
                "PIIMaskingResponseMiddleware: ошибка маскировки %s, payload "
                "пропущен без изменений: %s",
                request.url.path,
                exc,
            )
            body_iter: Any = response
            body_iter.body_iterator = AsyncChunkIterator([body])
            return response

        response.headers["content-length"] = str(len(masked))
        body_iter = response
        body_iter.body_iterator = AsyncChunkIterator([masked])
        return response

    # ----------------------------------------------------------------- helpers

    @staticmethod
    def _is_enabled() -> bool:
        """Lazy-проверка feature-flag ``pii_response_middleware_enabled``."""
        try:
            from src.backend.core.config.features import feature_flags

            return bool(
                getattr(feature_flags, "pii_response_middleware_enabled", False)
            )
        except Exception as _:
            return False

    def _path_matches(self, path: str) -> bool:
        """True если path matches один из patterns (или patterns пуст)."""
        if not self._path_patterns:
            return True
        return any(p.search(path) for p in self._path_patterns)

    @staticmethod
    def _mask_json_bytes(raw: bytes) -> bytes:
        """Парсит JSON, применяет :meth:`PIIMasker.mask_dict`, сериализует обратно."""
        import orjson

        text = raw.decode("utf-8")
        data: Any = orjson.loads(text)
        masker = default_masker()
        if isinstance(data, dict):
            masked = masker.mask_dict(data)
        else:
            # Top-level list / scalar — обход через приватный recursive helper.
            # mask_dict работает только с dict; для list/scalar используем
            # обёртку в одноразовый dict с key="_root" и распаковку.
            masked = masker.mask_dict({"_root": data})["_root"]
        return orjson.dumps(masked)

    @staticmethod
    async def _capture_body(response: Response) -> bytes:
        """Собирает body_iterator в bytes (для дальнейшей трансформации)."""
        chunks: list[bytes] = []
        async for chunk in response.body_iterator:  # type: ignore[attr-defined]
            chunks.append(chunk)
        return b"".join(chunks)
