"""S171 M6 — FileListProcessor (gap fill).

Glob-поиск файлов. async via ``asyncio.to_thread``.
Капабилити: rpa.file.list (read-only, low risk).

ADR-0390: три барьера вместо одного — traversal (``..``) в самом паттерне
запрещён, каждый найденный файл проверяется по allowlist, количество
результатов ограничено.
"""

from __future__ import annotations

import asyncio
import glob
import os
from typing import TYPE_CHECKING, Any, ClassVar

from src.backend.core.logging import get_logger
from src.backend.dsl.engine.processors._path_safety import (
    PathTraversalError,
    is_path_allowed,
    validate_path,
)
from src.backend.dsl.engine.processors.base import BaseProcessor

if TYPE_CHECKING:
    from src.backend.dsl.engine.context import ExecutionContext
    from src.backend.dsl.engine.exchange import Exchange

_rpa_logger = get_logger("dsl.rpa")

# Magic-символы glob-паттерна (см. :func:`glob.glob`).
_GLOB_MAGIC_CHARS = ("*", "?", "[")

#: Максимум файлов в одном ответе (ADR-0390). Без лимита glob по
#: ``/data/uploads/**`` может вернуть сотни тысяч путей и положить маршрут
#: по памяти.
_MAX_FILE_LIST_RESULTS = 1000


class FileListLimitError(ValueError):
    """Результатов glob больше ``_MAX_FILE_LIST_RESULTS`` (ADR-0390)."""


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

    @staticmethod
    def _has_traversal(pattern: str) -> bool:
        """True, если в паттерне есть сегмент ``..`` (ADR-0390).

        Статический префикс паттерна проверяется по allowlist, но сам
        паттерн мог содержать ``..``: ``/tmp/allow/sub/../../etc/hostname``
        проходил проверку каталога-префикса и выдавал файлы вне allowlist.

        Args:
            pattern: Glob-паттерн.

        Returns:
            ``True`` — паттерн содержит traversal.

        """
        return ".." in pattern.replace("\\", "/").split("/")

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
        # ограничивает факт вызова, allowlist — путь.

        # ADR-0390: traversal в самом паттерне запрещён — проверка только
        # статического префикса была обходима (``..`` внутри паттерна).
        if self._has_traversal(pattern):
            exchange.fail("file_list blocked: path traversal in pattern")
            return

        try:
            validate_path(_static_dir_prefix(pattern))
        except PathTraversalError as exc:
            exchange.fail(f"file_list blocked: {exc}")
            return

        # Async glob (file I/O в thread pool) + проверка каждого результата
        # по allowlist (ADR-0390) + лимит количества результатов.
        try:
            files = await asyncio.to_thread(self._glob_allowed, pattern, self.recursive)
        except PathTraversalError as exc:
            exchange.fail(f"file_list blocked: {exc}")
            return
        except FileListLimitError as exc:
            exchange.fail(f"file_list blocked: {exc}")
            return

        _rpa_logger.info("file_list pattern=%s count=%d", pattern, len(files))
        # Write to body via dotted path (set_result handles it)
        self.set_result(exchange, self.target, sorted(files))

    @staticmethod
    def _glob_allowed(pattern: str, recursive: bool) -> list[str]:
        """Glob + allowlist-проверка каждого результата + лимит (ADR-0390).

        Args:
            pattern: Glob-паттерн.
            recursive: Рекурсивный поиск (``**``).

        Returns:
            Список найденных файлов (все — внутри allowlist).

        Raises:
            PathTraversalError: Найден файл вне allowlist.
            FileListLimitError: Результатов больше ``_MAX_FILE_LIST_RESULTS``.

        """
        found: list[str] = []
        for match in glob.iglob(pattern, recursive=recursive):
            if not is_path_allowed(match):
                raise PathTraversalError(
                    f"glob result outside allowed directories: {match}"
                )
            found.append(match)
            if len(found) > _MAX_FILE_LIST_RESULTS:
                raise FileListLimitError(
                    f"glob returned more than {_MAX_FILE_LIST_RESULTS} files "
                    f"(pattern={pattern!r})"
                )
        return found
