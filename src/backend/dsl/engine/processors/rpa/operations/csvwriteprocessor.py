"""S171 M6.1 — CsvWriteProcessor (gap fill).

Async CSV write via :mod:`csv` + :func:`asyncio.to_thread`.
Capability: rpa.file.csv.write (medium risk — file creation).

ADR-0367:
- ``dst`` проверяется по path-allowlist (``validate_path``);
- значения и заголовки нейтрализуют CSV formula-инъекцию (OWASP);
- колонки — union ключей всех строк (без ``ValueError`` на разнородных ключах).
"""

from __future__ import annotations

import asyncio
import csv
from collections.abc import Mapping
from typing import TYPE_CHECKING, Any, ClassVar

from src.backend.core.logging import get_logger
from src.backend.dsl.engine.processors.base import BaseProcessor

if TYPE_CHECKING:
    from src.backend.dsl.engine.context import ExecutionContext
    from src.backend.dsl.engine.exchange import Exchange

_rpa_logger = get_logger("dsl.rpa")

# ADR-0367: префиксы, которые Excel/LibreOffice трактуют как формулу.
_FORMULA_PREFIXES = ("=", "+", "-", "@")


def _neutralize_formula(value: Any) -> Any:
    """Нейтрализовать CSV formula-инъекцию (OWASP CSV Injection).

    Строковое значение, начинающееся с ``=``/``+``/``-``/``@``, получает
    префикс ``'`` — иначе при открытии файла в Excel/LibreOffice ячейка
    исполняется как формула. Числа и прочие типы не изменяются.

    Args:
        value: Значение ячейки (или имя колонки).

    Returns:
        Безопасное значение ячейки.

    """
    if isinstance(value, str) and value.startswith(_FORMULA_PREFIXES):
        return "'" + value
    return value


def _collect_fieldnames(rows: list[Any]) -> list[Any]:
    """Собрать union колонок по всем строкам (порядок первого появления).

    Args:
        rows: Строки CSV (каждая — Mapping).

    Returns:
        Список исходных имён колонок (без нейтрализации).

    Raises:
        ValueError: Если строка не является Mapping.

    """
    for row in rows:
        if not isinstance(row, Mapping):
            raise ValueError(
                "csv_write expects rows as mappings (dict), got "
                f"{type(row).__name__}"
            )
    return list(dict.fromkeys(key for row in rows for key in row))


def _header_names(fieldnames: list[Any]) -> list[Any]:
    """Нейтрализовать имена колонок (header — тоже ячейка, формула возможна).

    Args:
        fieldnames: Исходные имена колонок.

    Returns:
        Безопасные имена колонок.

    Raises:
        ValueError: Если после нейтрализации имена колонок совпали
            (иначе данные молча перезаписывались бы).

    """
    names = [_neutralize_formula(name) for name in fieldnames]
    if len(set(names)) != len(names):
        raise ValueError(
            "csv_write: column names collide after formula neutralization"
        )
    return names


class CsvWriteProcessor(BaseProcessor):
    """Write list of dicts → CSV file.

    Args:
        dst: Path для output CSV (проверяется по path-allowlist).
        rows: List of dicts (header = union ключей всех dict'ов).
        delimiter: CSV delimiter (default ``","``).

    """

    required_capability: ClassVar[str | None] = "rpa.file.csv.write"
    audit_event: str | None = "rpa.file.csv.write"

    def __init__(
        self,
        *,
        dst: str,
        rows: list[dict[str, Any]],
        delimiter: str = ",",
        name: str | None = None,
    ) -> None:
        super().__init__(name=name or "csv_write")
        self.dst = dst
        self.rows = rows
        self.delimiter = delimiter

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        """Метод process (см. signature)."""
        if not await self.auth_check(exchange, action="write"):
            return

        # Второй независимый барьер безопасности: capability ограничивает
        # факт вызова, allowlist — путь (иначе пишем произвольный файл ФС).
        from src.backend.dsl.engine.processors._path_safety import (
            PathTraversalError,
            validate_path,
        )

        try:
            safe_dst = validate_path(self.dst)
        except PathTraversalError as exc:
            exchange.fail(f"csv_write blocked: {exc}")
            return

        # Union колонок считаем до создания файла — не-Mapping строка не
        # должна оставлять после себя пустой файл.
        fieldnames = _collect_fieldnames(self.rows)
        header = _header_names(fieldnames)

        if not self.rows:
            await asyncio.to_thread(
                lambda: open(safe_dst, "w", encoding="utf-8").close()
            )
            return

        def _write() -> None:
            with open(safe_dst, "w", encoding="utf-8", newline="") as f:
                writer = csv.writer(f, delimiter=self.delimiter)
                writer.writerow(header)
                for row in self.rows:
                    writer.writerow(
                        [_neutralize_formula(row.get(key, "")) for key in fieldnames]
                    )

        await asyncio.to_thread(_write)
        _rpa_logger.info("csv_write dst=%s rows=%d", safe_dst, len(self.rows))
        self.set_result(exchange, "body.written", len(self.rows))
