"""S65 W2 — ArchiveProcessor extracted from rpa/operations.py.

Per-processor file split.

ADR-0367: zip-slip на создании архива + капы на распаковку (zip/tar-bomb).
"""

from __future__ import annotations

import asyncio
import os
from typing import Any, ClassVar

from src.backend.core.logging import get_logger
from src.backend.dsl.engine.context import ExecutionContext
from src.backend.dsl.engine.exchange import Exchange
from src.backend.dsl.engine.processors.base import BaseProcessor

_rpa_logger = get_logger("dsl.rpa")

# ADR-0367: капы на распаковку. Модульные константы (без новых config-ключей):
# zip/tar-bomb распаковывается целиком в память → нужен жёсткий потолок.
_MAX_UNPACK_BYTES = 64 * 1024 * 1024
_MAX_ENTRIES = 1000


class ArchiveProcessor(BaseProcessor):
    """ZIP/TAR архивация и распаковка.

    mode="extract": body=bytes → list of {"name": str, "data": bytes}
    mode="create": body=list of {"name": str, "data": bytes} → bytes

    ADR-0367: имя записи при создании санитизируется (``os.path.basename``),
    распаковка ограничена по числу записей и суммарному размеру.
    """

    required_capability: ClassVar[str | None] = "rpa.archive.execute"
    audit_event: str | None = "rpa.archive.execute"

    def __init__(
        self, *, mode: str = "extract", format: str = "zip", name: str | None = None
    ) -> None:
        super().__init__(name=name or f"archive:{mode}:{format}")
        self._mode = mode
        self._format = format

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        """Обработать exchange согласно логике процессора. Читает body / properties, мутирует exchange, выбрасывает exceptions для error handling pipeline."""
        if not await self.auth_check(exchange, action="execute"):
            return
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

    @staticmethod
    def _safe_entry_name(raw: Any) -> str:
        """Санитизировать имя записи архива (защита от zip-slip).

        Args:
            raw: Имя записи как его задал вызывающий.

        Returns:
            Базовое имя записи (без директорий).

        Raises:
            ValueError: Если после ``basename`` имя пустое или ссылается на
                каталог (``.`` / ``..``).

        """
        name = os.path.basename(str(raw))
        if not name or name in {".", ".."}:
            raise ValueError(f"unsafe archive entry name: {raw!r}")
        return name

    @staticmethod
    def _check_limits(sizes: list[int]) -> None:
        """Проверить капы на число записей и суммарный размер ДО чтения.

        Args:
            sizes: Заявленные размеры записей (байт).

        Raises:
            ValueError: Превышен лимит записей или суммарного размера.

        """
        if len(sizes) > _MAX_ENTRIES:
            raise ValueError(
                f"archive too many entries: {len(sizes)} > {_MAX_ENTRIES}"
            )
        total = sum(sizes)
        if total > _MAX_UNPACK_BYTES:
            raise ValueError(
                f"archive too large: {total} bytes > {_MAX_UNPACK_BYTES} bytes"
            )
        for size in sizes:
            if size > _MAX_UNPACK_BYTES:
                raise ValueError(
                    f"archive entry too large: {size} bytes > {_MAX_UNPACK_BYTES} bytes"
                )

    def _extract(self, data: bytes) -> list[dict[str, Any]]:
        import io

        files: list[dict[str, Any]] = []
        if self._format == "zip":
            import zipfile

            with zipfile.ZipFile(io.BytesIO(data)) as zf:
                infos = [info for info in zf.infolist() if not info.is_dir()]
                # Капы проверяются ДО чтения содержимого (zip-bomb).
                self._check_limits([info.file_size for info in infos])
                for info in infos:
                    # ponytail: sanitize filename to prevent Zip Slip
                    name = os.path.basename(info.filename)
                    if name and not name.startswith("."):
                        with zf.open(info) as fh:
                            # Per-entry cap: читаем не больше капа (+1 байт
                            # для обнаружения превышения).
                            payload = fh.read(_MAX_UNPACK_BYTES + 1)
                        if len(payload) > _MAX_UNPACK_BYTES:
                            raise ValueError(
                                f"archive entry too large: {info.file_size} bytes "
                                f"> {_MAX_UNPACK_BYTES} bytes"
                            )
                        files.append(
                            {
                                "name": name,
                                "data": payload,
                                "size": info.file_size,
                            }
                        )
        else:
            import tarfile

            with tarfile.open(fileobj=io.BytesIO(data)) as tf:
                members = [member for member in tf.getmembers() if member.isfile()]
                # Капы проверяются ДО чтения содержимого (tar-bomb).
                self._check_limits([member.size for member in members])
                for member in members:
                    # ponytail: sanitize filename to prevent Zip Slip
                    name = os.path.basename(member.name)
                    if name and not name.startswith("."):
                        f = tf.extractfile(member)
                        payload = f.read(_MAX_UNPACK_BYTES + 1) if f else b""
                        if len(payload) > _MAX_UNPACK_BYTES:
                            raise ValueError(
                                f"archive entry too large: {member.size} bytes "
                                f"> {_MAX_UNPACK_BYTES} bytes"
                            )
                        files.append(
                            {
                                "name": name,
                                "data": payload,
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
                    zf.writestr(self._safe_entry_name(item["name"]), data)
        else:
            import tarfile

            with tarfile.open(fileobj=buf, mode="w:gz") as tf:
                for item in items:
                    ti = tarfile.TarInfo(name=self._safe_entry_name(item["name"]))
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
