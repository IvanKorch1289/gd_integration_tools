"""DSL processor ``mask_pii`` — явная маскировка PII в request/response.

Wave ``[wave:s8/k1-w4-pii-dsl-step]``.

Используется автором маршрута, когда требуется отдать данные внешнему
сервису / логгеру / DLQ без чувствительной информации. В отличие от
:func:`mask_pii` из ``infrastructure/observability/pii_filter.py``
(structlog-processor для логов), этот шаг работает на уровне DSL и
маскирует выбранные части ``Exchange``: body, headers, query, path.

Контракт YAML::

    steps:
      - mask_pii: { targets: ["body", "headers"] }
      - mask_pii: { targets: ["body"], fields: ["email", "phone"] }
      - mask_pii:
          targets: ["body"]
          patterns: ["session_id=\\d+"]
          replacement: "<masked>"

Контракт Python (через :meth:`IntegrationMixin.mask_pii`)::

    RouteBuilder("orders") \\
        .from_("http:POST /api/v1/orders") \\
        .mask_pii(targets=["body", "headers"]) \\
        .dispatch_action("orders.add")

Маскировка применяется in-place к ``exchange.in_message.body`` /
``exchange.in_message.headers`` и к ``request`` из properties (для
``query`` / ``path`` параметров). После выполнения процессора
последующие шаги получают уже маскированные данные.

Размещение: top-level в ``processors/`` (рядом с
``validate_response.py`` / ``webhook_signature.py``) — потому что
``security.py`` уже занят :class:`AuthValidateProcessor`'ом.
"""

from __future__ import annotations

import re
from typing import TYPE_CHECKING, Any

from src.backend.core.security.pii_masker import PIIMasker, build_default_patterns
from src.backend.dsl.engine.processors.base import BaseProcessor
from src.backend.dsl.registry import processor

if TYPE_CHECKING:
    from src.backend.dsl.engine.context import ExecutionContext
    from src.backend.dsl.engine.exchange import Exchange


__all__ = ("MaskPiiProcessor", "ALLOWED_TARGETS")


# Допустимые цели маскировки. Расширяется только через явное согласование —
# whitelist защищает от опечаток в YAML.
ALLOWED_TARGETS: frozenset[str] = frozenset({"body", "headers", "query", "path"})


@processor(
    "mask_pii",
    namespace="core",
    spec_schema={
        "type": "object",
        "properties": {
            "targets": {
                "type": "array",
                "items": {"type": "string", "enum": sorted(ALLOWED_TARGETS)},
                "minItems": 1,
            },
            "fields": {"type": ["array", "null"], "items": {"type": "string"}},
            "replacement": {"type": "string"},
            "patterns": {"type": ["array", "null"], "items": {"type": "string"}},
        },
        "required": ["targets"],
    },
    meta={"tier": 1, "category": "security"},
    tags=("pii", "security", "masking"),
)
class MaskPiiProcessor(BaseProcessor):
    """Маскирует PII в выбранных частях ``Exchange``.

    Args:
        targets: Список частей exchange для маскировки. Допустимые
            значения: ``body``, ``headers``, ``query``, ``path``.
            ``query`` и ``path`` маскируются в request объекте из
            ``exchange.properties['request']`` (если он есть).
        fields: Опц. список конкретных полей (по ключу dict). Если
            ``None`` — маскируются все строковые значения.
        replacement: Строка-заменитель (default ``"***"``).
        patterns: Опц. список regex-строк для custom-patterns. Если
            задан — используется ВМЕСТО дефолтных (как полная замена).
            Если ``None`` — используются дефолтные patterns из
            :func:`build_default_patterns`.
        name: Имя процессора (для логирования).
    """

    def __init__(
        self,
        *,
        targets: list[str],
        fields: list[str] | None = None,
        replacement: str = "***",
        patterns: list[str] | None = None,
        name: str | None = None,
    ) -> None:
        super().__init__(name=name or "mask_pii")
        if not targets:
            raise ValueError("mask_pii: targets must be non-empty list")
        unknown = set(targets) - ALLOWED_TARGETS
        if unknown:
            allowed = ", ".join(sorted(ALLOWED_TARGETS))
            raise ValueError(
                f"mask_pii: unknown targets {sorted(unknown)!r}, allowed: {allowed}"
            )
        self._targets = tuple(targets)
        self._fields = list(fields) if fields else None
        self._replacement = replacement
        self._raw_patterns = list(patterns) if patterns else None
        self._masker = self._build_masker()

    def _build_masker(self) -> PIIMasker:
        """Создаёт :class:`PIIMasker` с custom или дефолтными patterns."""
        if self._raw_patterns is None:
            return PIIMasker(replacement=self._replacement)
        compiled: dict[str, re.Pattern[str]] = {}
        for idx, raw in enumerate(self._raw_patterns):
            try:
                compiled[f"custom_{idx}"] = re.compile(raw)
            except re.error as exc:
                raise ValueError(
                    f"mask_pii: invalid regex at index {idx}: {raw!r} ({exc})"
                ) from exc
        return PIIMasker(patterns=compiled, replacement=self._replacement)

    # ── Public processor entry point ──

    async def process(
        self, exchange: "Exchange[Any]", context: "ExecutionContext"
    ) -> None:
        """Применяет маскировку к указанным targets."""
        for target in self._targets:
            match target:
                case "body":
                    self._mask_body(exchange)
                case "headers":
                    self._mask_headers(exchange)
                case "query":
                    self._mask_request_attr(exchange, attr="query_params")
                case "path":
                    self._mask_request_attr(exchange, attr="path_params")

    # ── Target-specific maskers ──

    def _mask_body(self, exchange: "Exchange[Any]") -> None:
        body = exchange.in_message.body
        if body is None:
            return
        if isinstance(body, dict):
            exchange.in_message.body = self._masker.mask_dict(body, self._fields)
        elif isinstance(body, list):
            exchange.in_message.body = [
                self._masker.mask_dict(item, self._fields)
                if isinstance(item, dict)
                else self._masker.mask_text(item)
                if isinstance(item, str)
                else item
                for item in body
            ]
        elif isinstance(body, str):
            exchange.in_message.body = self._masker.mask_text(body)
        # bytes / прочие — не трогаем (передаём как есть)

    def _mask_headers(self, exchange: "Exchange[Any]") -> None:
        headers = exchange.in_message.headers
        if not headers:
            return
        masked = self._masker.mask_dict(headers, self._fields)
        exchange.in_message.headers = masked

    def _mask_request_attr(self, exchange: "Exchange[Any]", *, attr: str) -> None:
        """Маскирует ``request.query_params`` / ``request.path_params``.

        request обычно хранится в ``exchange.properties['request']`` либо в
        :class:`Message.headers['request']` host-ом транспорта. Если объект
        отсутствует — silent no-op (route мог быть запущен по таймеру).
        """
        request = exchange.get_property("request") or exchange.in_message.headers.get(
            "request"
        )
        if request is None:
            return
        params = getattr(request, attr, None)
        if params is None:
            return
        if isinstance(params, dict):
            masked = self._masker.mask_dict(params, self._fields)
            # FastAPI/Starlette request.query_params/path_params могут быть
            # immutable QueryParams; пробуем set обратно, если не выйдет —
            # пишем в properties для downstream-консумеров.
            try:
                setattr(request, attr, masked)
            except (AttributeError, TypeError):
                exchange.set_property(f"masked_{attr}", masked)

    # ── Serialization ──

    def to_spec(self) -> dict[str, Any]:
        """Round-trip сериализация для YAML."""
        spec: dict[str, Any] = {
            "targets": list(self._targets),
            "replacement": self._replacement,
        }
        if self._fields is not None:
            spec["fields"] = list(self._fields)
        if self._raw_patterns is not None:
            spec["patterns"] = list(self._raw_patterns)
        return {"mask_pii": spec}


# Сохраняем reference на patterns для unit-тестов / диагностики.
_ = build_default_patterns  # re-export hook (для документации)
