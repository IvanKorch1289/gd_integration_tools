"""S65 W2 — FileMoveProcessor extracted from rpa/operations.py.

Per-processor file split.
"""

from __future__ import annotations

from typing import Any

from src.backend.core.logging import get_logger
from src.backend.dsl.engine.context import ExecutionContext
from src.backend.dsl.engine.exchange import Exchange
from src.backend.dsl.engine.processors.base import BaseProcessor

_rpa_logger = get_logger("dsl.rpa")


class FileMoveProcessor(BaseProcessor):
    """Copy, move, or rename файлов.

    Params: src, dst, mode="copy"|"move"|"rename".
    Значения можно передать через body (dict с ключами src, dst).
    """

    def __init__(
        self,
        src: str | None = None,
        dst: str | None = None,
        *,
        mode: str = "copy",
        name: str | None = None,
    ) -> None:
        super().__init__(name=name or f"file_{mode}")
        self._src = src
        self._dst = dst
        self._mode = mode

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        """Обработать exchange согласно логике процессора. Читает body / properties, мутирует exchange, выбрасывает exceptions для error handling pipeline."""
        import shutil

        body = exchange.in_message.body
        src = self._src or (body.get("src") if isinstance(body, dict) else None)
        dst = self._dst or (body.get("dst") if isinstance(body, dict) else None)
        if not src or not dst:
            exchange.fail("file_move requires src and dst")
            return
        try:
            # ponytail: wrap blocking I/O in asyncio.to_thread to avoid blocking event loop
            import asyncio

            if self._mode == "move":
                await asyncio.to_thread(shutil.move, src, dst)
            elif self._mode == "rename":
                import os

                await asyncio.to_thread(os.rename, src, dst)
            else:
                await asyncio.to_thread(shutil.copy2, src, dst)
            exchange.set_property(
                "file_operation", {"mode": self._mode, "src": src, "dst": dst}
            )
        except (FileNotFoundError, PermissionError, OSError) as exc:
            exchange.fail(f"File {self._mode} failed: {exc}")

    def to_spec(self) -> dict[str, Any] | None:
        """Сериализовать конфигурацию процессора в dict. Возвращает None для non-serializable runtime state."""
        spec: dict[str, Any] = {}
        if self._src is not None:
            spec["src"] = self._src
        if self._dst is not None:
            spec["dst"] = self._dst
        if self._mode != "copy":
            spec["mode"] = self._mode
        return {"file_move": spec}
