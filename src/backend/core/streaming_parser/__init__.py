"""Streaming Parser — bounded-memory CSV/JSON parser (Wave 2 DX #42).

Проблема (DEEP_AUDIT):
    Большие CSV/JSON файлы парсятся в память целиком:
    - 100MB CSV → 100MB RAM allocation.
    - Память кончается, OOM kill.
    - Worker hung во время парсинга.

Решение:
    ``StreamingParser`` — chunked iterator-based parsing:

    1. ``ParsedRecord`` — единичная запись (dict-like).
    2. ``StreamingCSVParser`` — row-by-row iterator (uses stdlib ``csv``).
    3. ``StreamingJSONParser`` — array-of-objects JSON parser.
    4. ``parse_file(path, max_rows=None)`` → iterator.
    5. Bounded memory: читает по chunk_size bytes.

Использование::

    from src.backend.core.streaming_parser import (
        StreamingCSVParser, StreamingJSONParser, ParsedRecord,
    )

    parser = StreamingCSVParser()
    for record in parser.parse_file("big.csv", chunk_size=8192):
        # record is dict[str, str].
        process(record)

    json_parser = StreamingJSONParser()
    for record in json_parser.parse_file("big.json", chunk_size=16384):
        process(record)
"""

from __future__ import annotations

from src.backend.core.streaming_parser.parsers import (
    ParsedRecord,
    StreamingCSVParser,
    StreamingJSONParser,
    get_csv_parser,
    get_json_parser,
)

__all__ = (
    "ParsedRecord",
    "StreamingCSVParser",
    "StreamingJSONParser",
    "get_csv_parser",
    "get_json_parser",
)
