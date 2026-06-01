"""DSL-процессор ``webdav_io`` — WebDAV upload/download/list через webdav4.

Wave ``[wave:s5/k3-w3-processor-pack-3]``.

Использует библиотеку ``webdav4`` (lazy-import). Поддерживает 4 операции:
``upload`` / ``download`` / ``list`` / ``delete``.

Контракт DSL::

    .webdav_io(
        url="https://dav.example.com",
        auth=("user", "pass"),
        mode="upload",
        remote_path="/folder/file.txt",
        source="body.content",
    )

Feature flag: ``feature_flags.proc_webdav`` (default-OFF).
"""

from __future__ import annotations

import asyncio
import io
from typing import TYPE_CHECKING, Any, ClassVar

from src.backend.core.types.side_effect import SideEffectKind
from src.backend.dsl.engine.processors.base import BaseProcessor
from src.backend.dsl.registry import processor

if TYPE_CHECKING:
    from src.backend.dsl.engine.context import ExecutionContext
    from src.backend.dsl.engine.exchange import Exchange


__all__ = ("WebDavProcessor",)


_ALLOWED_MODES = frozenset({"upload", "download", "list", "delete"})


@processor(
    "webdav_io",
    namespace="core",
    spec_schema={
        "type": "object",
        "properties": {
            "url": {"type": "string"},
            "username": {"type": "string"},
            "password": {"type": "string"},
            "mode": {"type": "string", "enum": sorted(_ALLOWED_MODES)},
            "remote_path": {"type": "string"},
            "source": {"type": "string"},
            "to": {"type": "string"},
        },
        "required": ["url", "mode", "remote_path"],
    },
    capabilities=("net.outbound.webdav:external",),
    meta={"tier": 1, "category": "storage"},
    tags=("webdav", "storage", "io"),
)
class WebDavProcessor(BaseProcessor):
    """WebDAV-операции через ``webdav4`` (sync client + ``to_thread``).

    Args:
        url: Base URL WebDAV-сервера (``https://dav.example.com``).
        username: Логин.
        password: Пароль.
        mode: ``upload`` / ``download`` / ``list`` / ``delete``.
        remote_path: Путь на сервере (``/folder/file.txt``).
        source: Откуда читать данные для ``upload`` (``body``, ``body.<field>``).
        to: Куда положить результат (``body.<field>``).
    """

    side_effect: ClassVar[SideEffectKind] = SideEffectKind.SIDE_EFFECTING
    compensatable: ClassVar[bool] = False

    def __init__(
        self,
        url: str,
        mode: str,
        remote_path: str,
        *,
        username: str | None = None,
        password: str | None = None,
        source: str = "body",
        to: str = "body.webdav_result",
        name: str | None = None,
    ) -> None:
        super().__init__(name=name or f"webdav_io:{mode}")
        if mode not in _ALLOWED_MODES:
            raise ValueError(
                f"webdav_io: mode must be one of {sorted(_ALLOWED_MODES)}, got {mode!r}"
            )
        if not url:
            raise ValueError("webdav_io: url must be non-empty")
        if not remote_path:
            raise ValueError("webdav_io: remote_path must be non-empty")
        self._url = url
        self._mode = mode
        self._remote_path = remote_path
        self._username = username
        self._password = password
        self._source = source
        self._target = to

    def _resolve_source(self, exchange: "Exchange[Any]") -> Any:
        body = exchange.in_message.body
        if self._source == "body":
            return body
        if self._source.startswith("body."):
            return (
                body.get(self._source[len("body.") :])
                if isinstance(body, dict)
                else None
            )
        if self._source.startswith("properties."):
            return exchange.properties.get(self._source[len("properties.") :])
        return None

    def _apply_target(self, exchange: "Exchange[Any]", value: Any) -> None:
        if self._target.startswith("body."):
            field = self._target[len("body.") :]
            body = exchange.in_message.body
            if not isinstance(body, dict):
                body = {}
                exchange.in_message.body = body  
            body[field] = value
            return
        if self._target.startswith("properties."):
            field = self._target[len("properties.") :]
            exchange.set_property(field, value)
            return
        exchange.set_property(self._target, value)

    def _exec_sync(self, src_value: Any) -> Any:
        from webdav4.client import Client  

        auth = (
            (self._username, self._password)
            if self._username and self._password
            else None
        )
        client = Client(self._url, auth=auth)

        match self._mode:
            case "upload":
                if isinstance(src_value, str):
                    src_value = src_value.encode("utf-8")
                buf = io.BytesIO(
                    src_value if isinstance(src_value, bytes) else bytes(src_value)
                )
                client.upload_fileobj(buf, self._remote_path)
                return {"path": self._remote_path, "bytes": len(buf.getvalue())}
            case "download":
                buf = io.BytesIO()
                client.download_fileobj(self._remote_path, buf)
                return buf.getvalue()
            case "list":
                return client.ls(self._remote_path)
            case "delete":
                client.remove(self._remote_path)
                return {"path": self._remote_path, "deleted": True}
            case _:
                raise ValueError(f"Unsupported mode {self._mode!r}")

    async def process(
        self, exchange: "Exchange[Any]", context: "ExecutionContext"
    ) -> None:
        try:
            from src.backend.core.config.features import feature_flags

            if not feature_flags.proc_webdav:
                exchange.set_property("webdav_status", "skipped")
                return
        except Exception as _:  # noqa: BLE001
            pass

        src_value = self._resolve_source(exchange) if self._mode == "upload" else None
        try:
            result = await asyncio.to_thread(self._exec_sync, src_value)
        except ImportError as exc:
            exchange.fail(f"webdav_io: webdav4 not available: {exc}")
            return
        except Exception as exc:  # noqa: BLE001
            exchange.fail(f"webdav_io error: {exc}")
            return

        self._apply_target(exchange, result)

    def to_spec(self) -> dict[str, Any] | None:
        spec: dict[str, Any] = {
            "url": self._url,
            "mode": self._mode,
            "remote_path": self._remote_path,
        }
        if self._username:
            spec["username"] = self._username
        if self._password:
            spec["password"] = self._password
        if self._source != "body":
            spec["source"] = self._source
        if self._target != "body.webdav_result":
            spec["to"] = self._target
        return {"webdav_io": spec}
