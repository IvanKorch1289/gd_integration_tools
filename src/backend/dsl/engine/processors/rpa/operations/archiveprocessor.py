"""S65 W2 — ArchiveProcessor extracted from rpa/operations.py.

Per-processor file split.
"""

from __future__ import annotations

import asyncio
from typing import Any

from src.backend.core.logging import get_logger
from src.backend.dsl.engine.context import ExecutionContext
from src.backend.dsl.engine.exchange import Exchange
from src.backend.dsl.engine.processors.base import BaseProcessor

_rpa_logger = get_logger("dsl.rpa")


class ArchiveProcessor(BaseProcessor):
    """ZIP/TAR архивация и распаковка.

    mode="extract": body=bytes → list of {"name": str, "data": bytes}
    mode="create": body=list of {"name": str, "data": bytes} → bytes
    """

    def __init__(
        self, *, mode: str = "extract", format: str = "zip", name: str | None = None
    ) -> None:
        super().__init__(name=name or f"archive:{mode}:{format}")
        self._mode = mode
        self._format = format

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        """Обработать exchange согласно логике процессора. Читает body / properties, мутирует exchange, выбрасывает exceptions для error handling pipeline."""
        body = exchange.in_message.body
        if self._mode == "extract":
            if not isinstance(body, bytes):
                exchange.fail("archive extract expects bytes")
                return
            try:
                files = await asyncio.to_thread(self._extract, body)
                exchange.set_out(body=files, headers=dict(exchange.in_message.headers))
            except Exception as exc:
                exchange.fail(f"Archive extract failed: {exc}")
        elif self._mode == "create":
            if not isinstance(body, list):
                exchange.fail("archive create expects list of {name, data}")
                return
            try:
                result = await asyncio.to_thread(self._create, body)
                exchange.set_out(body=result, headers=dict(exchange.in_message.headers))
            except Exception as exc:
                exchange.fail(f"Archive create failed: {exc}")

    def _extract(self, data: bytes) -> list[dict[str, Any]]:
        import io
        import os

        files = []
        if self._format == "zip":
            import zipfile

            with zipfile.ZipFile(io.BytesIO(data)) as zf:
                for info in zf.infolist():
                    if not info.is_dir():
                        # ponytail: sanitize filename to prevent Zip Slip
                        name = info.filename
                        name = os.path.basename(name)
                        if name and not name.startswith("."):
                            files.append(
                                {
                                    "name": name,
                                    "data": zf.read(info),
                                    "size": info.file_size,
                                }
                            )
        else:
            import tarfile

            with tarfile.open(fileobj=io.BytesIO(data)) as tf:
                for member in tf.getmembers():
                    if member.isfile():
                        f = tf.extractfile(member)
                        # ponytail: sanitize filename to prevent Zip Slip
                        name = member.name
                        name = os.path.basename(name)
                        if name and not name.startswith("."):
                            files.append(
                                {
                                    "name": name,
                                    "data": f.read() if f else b"",
                                    "size": member.size,
                                }
                            )
        return files

    def _create(self, items: list[dict[str, Any]]) -> bytes:
        import io

        buf = io.BytesIO()
        if self._format == "zip":
            import zipfile

            with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
                for item in items:
                    data = item.get("data", item.get("content", b""))
                    zf.writestr(item["name"], data)
        else:
            import tarfile

            with tarfile.open(fileobj=buf, mode="w:gz") as tf:
                for item in items:
                    ti = tarfile.TarInfo(name=item["name"])
                    raw = item.get("data", item.get("content", b""))
                    data = raw if isinstance(raw, bytes) else raw.encode()
                    ti.size = len(data)
                    tf.addfile(ti, io.BytesIO(data))
        return buf.getvalue()

    def to_spec(self) -> dict[str, Any] | None:
        """Сериализовать конфигурацию процессора в dict. Возвращает None для non-serializable runtime state."""
        spec: dict[str, Any] = {}
        if self._mode != "extract":
            spec["mode"] = self._mode
        if self._format != "zip":
            spec["format"] = self._format
        return {"archive": spec}
