"""S171 M6 — FileListProcessor (gap fill).

Glob-поиск файлов. async via ``asyncio.to_thread``.
Капабилити: rpa.file.list (read-only, low risk).
"""

from __future__ import annotations

import asyncio
import glob
import os
from typing import TYPE_CHECKING, Any, ClassVar

from src.backend.core.logging import get_logger
from src.backend.dsl.engine.processors.base import BaseProcessor

if TYPE_CHECKING:
    from src.backend.dsl.engine.context import ExecutionContext
    from src.backend.dsl.engine.exchange import Exchange

_rpa_logger = get_logger("dsl.rpa")

# Magic-символы glob-паттерна (см. :func:`glob.glob`).
_GLOB_MAGIC_CHARS = ("*", "?", "[")


def _static_dir_prefix(pattern: str) -> str:
    """Каталог-часть glob-паттерна до первого magic-символа.

    Используется для path-allowlist: сам паттерн резолвить нельзя
    (``**/*.py`` не проходит ``Path.resolve``), а вот его статический
    префикс — можно.

    Важно: берётся именно *каталог* префикса, а не его начало. Иначе
    ``/data/uploads*/*.txt`` прошёл бы проверку по ``/data/uploads``,
    хотя glob матчит ещё и ``/data/uploads_backup/x.txt`` — уже вне
    allowlist.

    Args:
        pattern: Glob-паттерн.

    Returns:
        Каталог-путь для проверки allowlist. Для относительного паттерна
        без статического префикса (``"*.log"``) — ``"."`` (cwd).

    """
    cut = len(pattern)
    for magic in _GLOB_MAGIC_CHARS:
        pos = pattern.find(magic)
        if pos != -1:
            cut = min(cut, pos)
    if cut == len(pattern):
        # Magic-символов нет — паттерн литеральный, валидируем целиком.
        return pattern
    head = pattern[:cut].rpartition("/")[0]
    if head:
        return head
    # Паттерн относительный → каталог = cwd; абсолютный → корень.
    return "/" if pattern.startswith("/") else "."


class FileListProcessor(BaseProcessor):
    """Список файлов по glob-паттерну.

    Args:
        pattern: Glob-паттерн (например ``"/tmp/*.txt"``).
        recursive: ``**`` для рекурсивного поиска (default False).
        to: Куда записать список (default ``"body.files"``).

    """

    required_capability: ClassVar[str | None] = "rpa.file.list"
    audit_event: str | None = "rpa.file.list"

    def __init__(
        self,
        *,
        pattern: str | None = None,
        recursive: bool = False,
        to: str = "body.files",
        name: str | None = None,
    ) -> None:
        super().__init__(name=name or "file_list")
        self.pattern = pattern
        self.recursive = recursive
        self.target = to

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        """Метод process (см. signature)."""
        if not await self.auth_check(exchange, action="read"):
            return
        pattern = self.pattern or exchange.in_message.body.get("pattern")  # type: ignore[union-attr]
        if not isinstance(pattern, str) or not pattern:
            raise ValueError("FileListProcessor: pattern обязателен")
        if self.recursive and "**" not in pattern:
            pattern = os.path.join(pattern, "**")

        # Второй независимый барьер безопасности: capability (``rpa.file.list``)
        # ограничивает факт вызова, allowlist — путь. Проверяем статический
        # префикс glob-паттерна (каталог), а не сам паттерн.
        # ponytail: симлинки внутри allowlist проверяются по текстовому пути,
        # а не по resolved (как в FileReadProcessor). Предел: glob может
        # вернуть ссылку наружу. Апгрейд: validate_path по каждому результату.
        from src.backend.dsl.engine.processors._path_safety import (
            PathTraversalError,
            validate_path,
        )

        try:
            validate_path(_static_dir_prefix(pattern))
        except PathTraversalError as exc:
            exchange.fail(f"file_list blocked: {exc}")
            return

        # Async glob (file I/O в thread pool)
        files = await asyncio.to_thread(glob.glob, pattern, recursive=self.recursive)
        _rpa_logger.info("file_list pattern=%s count=%d", pattern, len(files))
        # Write to body via dotted path (set_result handles it)
        self.set_result(exchange, self.target, sorted(files))
