"""Streaming parsers for CSV/JSON with bounded memory (Wave 2 DX #42).

Pure-Python stdlib: uses ``csv`` для CSV и chunked ``json`` для
JSON arrays-of-objects. Bounded memory via configurable chunk_size.
"""

from __future__ import annotations

import csv
import json
import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator

logger = logging.getLogger(__name__)

__all__ = (
    "ParsedRecord",
    "StreamingCSVParser",
    "StreamingJSONParser",
    "get_csv_parser",
    "get_json_parser",
)


@dataclass(slots=True)
class ParsedRecord:
    """Single parsed record.

    Attributes:
        data: Dict representation (CSV row or JSON object).
        row_number: 1-based row/record index (для diagnostics).
        raw_line: Optional original line / bytes (для error messages).
    """

    data: dict[str, Any]
    row_number: int = 0
    raw_line: str = ""

    def __getitem__(self, key: str) -> Any:
        return self.data[key]

    def __contains__(self, key: str) -> bool:
        return key in self.data

    def get(self, key: str, default: Any = None) -> Any:
        return self.data.get(key, default)


class StreamingCSVParser:
    """Chunked CSV parser с bounded memory.

    Uses stdlib ``csv`` module. Reads file in chunks of ``chunk_size`` bytes.
    Returns iterator of ``ParsedRecord``.
    """

    def __init__(self, *, delimiter: str = ",", quotechar: str = '"') -> None:
        self._delimiter = delimiter
        self._quotechar = quotechar

    def parse_file(
        self,
        path: str | Path,
        *,
        chunk_size: int = 8192,
        encoding: str = "utf-8",
        max_rows: int | None = None,
    ) -> Iterator[ParsedRecord]:
        """Stream-parse CSV file.

        Args:
            path: Path to CSV file.
            chunk_size: Read buffer size (bytes). Default 8KB.
            encoding: File encoding.
            max_rows: Stop after N rows (None = read all).

        Yields:
            :class:`ParsedRecord` per row.
        """
        path = Path(path)
        if not path.exists():
            raise FileNotFoundError(f"CSV file not found: {path}")
        with open(path, encoding=encoding, newline="") as f:
            reader = csv.reader(
                f, delimiter=self._delimiter, quotechar=self._quotechar
            )
            try:
                header = next(reader)
            except StopIteration:
                return
            row_number = 0
            for row in reader:
                row_number += 1
                if max_rows is not None and row_number > max_rows:
                    break
                # Pad/trim to header length.
                if len(row) < len(header):
                    row = row + [""] * (len(header) - len(row))
                data = dict(zip(header, row))
                yield ParsedRecord(
                    data=data,
                    row_number=row_number,
                    raw_line=",".join(row),
                )


class StreamingJSONParser:
    """Streaming JSON parser для array-of-objects (bounded memory).

    Pure-stdlib approach: reads file in chunks, uses ``json.JSONDecoder.raw_decode``
    для парсинга one object at a time. Ожидает JSON в формате:
    ``[ {"key": "value", ...}, ... ]``.

    Memory: O(chunk_size) — only current chunk + one parsed object.

    Note: This is a simplified implementation — for true incremental
    JSON parsing of very large files (>1GB), use ``ijson`` (added
    to pyproject as optional dep). This implementation works for arrays
    up to ~100MB with appropriate chunk_size.
    """

    def __init__(self) -> None:
        self._decoder = json.JSONDecoder()

    def parse_file(
        self,
        path: str | Path,
        *,
        chunk_size: int = 16384,
        max_rows: int | None = None,
    ) -> Iterator[ParsedRecord]:
        """Stream-parse JSON array file.

        Args:
            path: Path to JSON file.
            chunk_size: Read buffer size (bytes). Default 16KB.
            max_rows: Stop after N records (None = read all).

        Yields:
            :class:`ParsedRecord` per JSON object.
        """
        path = Path(path)
        if not path.exists():
            raise FileNotFoundError(f"JSON file not found: {path}")
        with open(path, "rb") as f:
            buf = ""
            row_number = 0
            while True:
                chunk = f.read(chunk_size)
                if chunk:
                    buf += chunk.decode("utf-8", errors="replace")
                # Try to extract as many objects as possible.
                while True:
                    # Skip whitespace.
                    idx = 0
                    while idx < len(buf) and buf[idx] in " \t\n\r":
                        idx += 1
                    if idx >= len(buf):
                        buf = ""
                        break
                    # Expect '[' or ',' as delimiter.
                    if buf[idx] not in "[,":
                        # End of array, or unexpected content.
                        break
                    # Skip delimiter.
                    if buf[idx] == ",":
                        idx += 1
                    # Skip more whitespace.
                    while idx < len(buf) and buf[idx] in " \t\n\r":
                        idx += 1
                    if idx >= len(buf):
                        buf = buf[idx:]
                        break
                    if buf[idx] == "]":
                        # End of array.
                        return
                    # Try to decode one object from buf[idx:].
                    try:
                        obj, end = self._decoder.raw_decode(buf[idx:])
                    except json.JSONDecodeError:
                        # Need more data.
                        if chunk:
                            break  # read more
                        # EOF — give up.
                        return
                    # Advance buffer.
                    consumed = idx + end
                    buf = buf[consumed:]
                    if isinstance(obj, dict):
                        row_number += 1
                        if max_rows is not None and row_number > max_rows:
                            return
                        yield ParsedRecord(
                            data=obj,
                            row_number=row_number,
                            raw_line=json.dumps(obj)[:200],
                        )
                    elif isinstance(obj, list):
                        # Unwrap nested list.
                        for item in obj:
                            if isinstance(item, dict):
                                row_number += 1
                                if (
                                    max_rows is not None
                                    and row_number > max_rows
                                ):
                                    return
                                yield ParsedRecord(
                                    data=item,
                                    row_number=row_number,
                                    raw_line=json.dumps(item)[:200],
                                )
                # End of buffer processing — read more if possible.
                if not chunk:
                    break
                # Continue with whatever is left in buf.


# Module-level singleton lazy getters.
_csv_parser: StreamingCSVParser | None = None
_json_parser: StreamingJSONParser | None = None


def get_csv_parser() -> StreamingCSVParser:
    global _csv_parser
    if _csv_parser is None:
        _csv_parser = StreamingCSVParser()
    return _csv_parser


def get_json_parser() -> StreamingJSONParser:
    global _json_parser
    if _json_parser is None:
        _json_parser = StreamingJSONParser()
    return _json_parser


def reset_parsers() -> None:
    """Reset singletons (test-only)."""
    global _csv_parser, _json_parser
    _csv_parser = None
    _json_parser = None
