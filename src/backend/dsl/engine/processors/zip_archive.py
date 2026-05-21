"""DSL-процессор ``zip_archive`` — упаковка/распаковка ZIP (stdlib zipfile).

Wave ``[wave:s5/k3-w2-processor-pack-2]``.

Поддерживает 2 операции:

* ``pack`` — из dict[str, bytes|str] (filename -> content) в zip bytes;
* ``unpack`` — из zip bytes в dict[str, bytes].

Использует только stdlib ``zipfile`` + ``io.BytesIO`` (без внешних зависимостей).

Контракт DSL::

    .zip_archive(mode="pack", source="body.files", to="body.archive")
    .zip_archive(mode="unpack", source="body.archive", to="body.files")

YAML::

    - zip_archive:
        mode: pack
        source: body.files
        to: body.archive

Feature flag: ``feature_flags.proc_zip_archive`` (default-OFF).
"""

from __future__ import annotations

import io
import zipfile
from typing import TYPE_CHECKING, Any

from src.backend.dsl.engine.processors.base import BaseProcessor
from src.backend.dsl.registry import processor

if TYPE_CHECKING:
    from src.backend.dsl.engine.context import ExecutionContext
    from src.backend.dsl.engine.exchange import Exchange


__all__ = ("ZipArchiveProcessor",)


_ALLOWED_MODES = frozenset({"pack", "unpack"})


@processor(
    "zip_archive",
    namespace="core",
    spec_schema={
        "type": "object",
        "properties": {
            "mode": {"type": "string", "enum": sorted(_ALLOWED_MODES)},
            "source": {"type": "string"},
            "to": {"type": "string"},
            "compression": {"type": "integer"},
        },
        "required": ["mode"],
    },
    meta={"tier": 1, "category": "io"},
    tags=("zip", "archive", "io"),
)
class ZipArchiveProcessor(BaseProcessor):
    """Pack/unpack ZIP-архива через stdlib ``zipfile``.

    Args:
        mode: ``pack`` или ``unpack``.
        source: Откуда читать данные (``body``, ``body.<field>``, ``properties.<name>``).
        to: Куда положить результат.
        compression: Уровень компрессии (``zipfile.ZIP_DEFLATED`` = 8).
    """

    def __init__(
        self,
        mode: str,
        *,
        source: str = "body",
        to: str = "body.zip_result",
        compression: int = zipfile.ZIP_DEFLATED,
        name: str | None = None,
    ) -> None:
        super().__init__(name=name or f"zip_archive:{mode}")
        if mode not in _ALLOWED_MODES:
            raise ValueError(f"zip_archive: mode must be 'pack'|'unpack', got {mode!r}")
        self._mode = mode
        self._source = source
        self._target = to
        self._compression = compression

    def _resolve_source(self, exchange: "Exchange[Any]") -> Any:
        body = exchange.in_message.body
        if self._source == "body":
            return body
        if self._source.startswith("body."):
            field = self._source[len("body.") :]
            return body.get(field) if isinstance(body, dict) else None
        if self._source.startswith("properties."):
            field = self._source[len("properties.") :]
            return exchange.properties.get(field)
        return None

    def _apply_target(self, exchange: "Exchange[Any]", value: Any) -> None:
        if self._target.startswith("body."):
            field = self._target[len("body.") :]
            body = exchange.in_message.body
            if not isinstance(body, dict):
                body = {}
                exchange.in_message.body = body  # type: ignore[assignment]
            body[field] = value
            return
        if self._target.startswith("properties."):
            field = self._target[len("properties.") :]
            exchange.set_property(field, value)
            return
        exchange.set_property(self._target, value)

    def _pack(self, files: dict[str, Any]) -> bytes:
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", self._compression) as zf:
            for filename, content in files.items():
                if isinstance(content, str):
                    content = content.encode("utf-8")
                zf.writestr(filename, content)
        return buf.getvalue()

    def _unpack(self, data: bytes) -> dict[str, bytes]:
        result: dict[str, bytes] = {}
        with zipfile.ZipFile(io.BytesIO(data), "r") as zf:
            for info in zf.infolist():
                if info.is_dir():
                    continue
                result[info.filename] = zf.read(info.filename)
        return result

    async def process(
        self, exchange: "Exchange[Any]", context: "ExecutionContext"
    ) -> None:
        try:
            from src.backend.core.config.features import feature_flags

            if not feature_flags.proc_zip_archive:
                exchange.set_property("zip_archive_status", "skipped")
                return
        except Exception:  # noqa: BLE001
            pass

        src_value = self._resolve_source(exchange)

        try:
            if self._mode == "pack":
                if not isinstance(src_value, dict):
                    exchange.fail(
                        "zip_archive pack: source must be dict[filename -> content]"
                    )
                    return
                result: Any = self._pack(src_value)
            else:  # unpack
                if not isinstance(src_value, (bytes, bytearray)):
                    exchange.fail("zip_archive unpack: source must be bytes")
                    return
                result = self._unpack(bytes(src_value))
        except zipfile.BadZipFile as exc:
            exchange.fail(f"zip_archive: bad zip — {exc}")
            return
        except Exception as exc:  # noqa: BLE001
            exchange.fail(f"zip_archive error: {exc}")
            return

        self._apply_target(exchange, result)

    def to_spec(self) -> dict[str, Any] | None:
        spec: dict[str, Any] = {"mode": self._mode}
        if self._source != "body":
            spec["source"] = self._source
        if self._target != "body.zip_result":
            spec["to"] = self._target
        if self._compression != zipfile.ZIP_DEFLATED:
            spec["compression"] = self._compression
        return {"zip_archive": spec}
