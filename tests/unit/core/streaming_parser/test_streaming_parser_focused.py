"""Focused tests for ``core.streaming_parser`` (Wave 2 DX #42)."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.backend.core.streaming_parser import (
    ParsedRecord,
    StreamingCSVParser,
    StreamingJSONParser,
    get_csv_parser,
    get_json_parser,
)
from src.backend.core.streaming_parser.parsers import reset_parsers


@pytest.fixture(autouse=True)
def _reset():
    reset_parsers()
    yield
    reset_parsers()


@pytest.fixture
def sample_csv(tmp_path: Path) -> Path:
    """Create sample CSV file."""
    p = tmp_path / "sample.csv"
    p.write_text(
        "id,name,age\n"
        "1,Alice,30\n"
        "2,Bob,25\n"
        "3,Charlie,35\n",
        encoding="utf-8",
    )
    return p


@pytest.fixture
def sample_json(tmp_path: Path) -> Path:
    """Create sample JSON array file."""
    p = tmp_path / "sample.json"
    p.write_text(
        json.dumps([
            {"id": 1, "name": "Alice", "tags": ["admin", "user"]},
            {"id": 2, "name": "Bob", "tags": ["user"]},
            {"id": 3, "name": "Charlie", "tags": ["guest"]},
        ]),
        encoding="utf-8",
    )
    return p


class TestParsedRecord:
    def test_init(self) -> None:
        r = ParsedRecord(data={"x": 1}, row_number=5)
        assert r.row_number == 5
        assert r.raw_line == ""

    def test_getitem(self) -> None:
        r = ParsedRecord(data={"a": 1, "b": 2})
        assert r["a"] == 1
        assert r["b"] == 2

    def test_contains(self) -> None:
        r = ParsedRecord(data={"x": 1})
        assert "x" in r
        assert "y" not in r

    def test_get(self) -> None:
        r = ParsedRecord(data={"x": 1})
        assert r.get("x") == 1
        assert r.get("y") is None
        assert r.get("y", "default") == "default"


class TestStreamingCSVParserInit:
    def test_init_defaults(self) -> None:
        p = StreamingCSVParser()
        assert p._delimiter == ","
        assert p._quotechar == '"'

    def test_custom_delimiter(self) -> None:
        p = StreamingCSVParser(delimiter=";")
        assert p._delimiter == ";"


class TestStreamingCSVParserFile:
    def test_missing_file(self, tmp_path: Path) -> None:
        p = StreamingCSVParser()
        with pytest.raises(FileNotFoundError):
            list(p.parse_file(tmp_path / "missing.csv"))

    def test_basic_parse(self, sample_csv: Path) -> None:
        p = StreamingCSVParser()
        records = list(p.parse_file(sample_csv))
        assert len(records) == 3
        assert records[0].data == {"id": "1", "name": "Alice", "age": "30"}
        assert records[0].row_number == 1
        assert records[2].row_number == 3

    def test_max_rows(self, sample_csv: Path) -> None:
        p = StreamingCSVParser()
        records = list(p.parse_file(sample_csv, max_rows=2))
        assert len(records) == 2

    def test_max_rows_one(self, sample_csv: Path) -> None:
        p = StreamingCSVParser()
        records = list(p.parse_file(sample_csv, max_rows=1))
        assert len(records) == 1
        assert records[0]["name"] == "Alice"

    def test_empty_file(self, tmp_path: Path) -> None:
        p = tmp_path / "empty.csv"
        p.write_text("", encoding="utf-8")
        records = list(StreamingCSVParser().parse_file(p))
        assert records == []

    def test_header_only(self, tmp_path: Path) -> None:
        p = tmp_path / "header.csv"
        p.write_text("a,b,c\n", encoding="utf-8")
        records = list(StreamingCSVParser().parse_file(p))
        assert records == []

    def test_padding_short_row(self, tmp_path: Path) -> None:
        p = tmp_path / "short.csv"
        p.write_text("a,b,c\n1,2\n", encoding="utf-8")
        records = list(StreamingCSVParser().parse_file(p))
        assert len(records) == 1
        assert records[0].data == {"a": "1", "b": "2", "c": ""}

    def test_truncating_long_row(self, tmp_path: Path) -> None:
        p = tmp_path / "long.csv"
        p.write_text("a,b\n1,2,3,4\n", encoding="utf-8")
        records = list(StreamingCSVParser().parse_file(p))
        # csv.reader keeps all extra columns as values in list; our zip
        # with header truncates. So data will be {"a": "1", "b": "2"}.
        assert records[0].data == {"a": "1", "b": "2"}

    def test_custom_delimiter(self, tmp_path: Path) -> None:
        p = tmp_path / "sc.csv"
        p.write_text("a;b;c\n1;2;3\n", encoding="utf-8")
        records = list(StreamingCSVParser(delimiter=";").parse_file(p))
        assert records[0].data == {"a": "1", "b": "2", "c": "3"}

    def test_quoted_csv(self, tmp_path: Path) -> None:
        p = tmp_path / "quoted.csv"
        p.write_text('a,b\n"hello, world",2\n', encoding="utf-8")
        records = list(StreamingCSVParser().parse_file(p))
        assert records[0].data == {"a": "hello, world", "b": "2"}

    def test_iterator_lazy(self, sample_csv: Path) -> None:
        """parse_file returns iterator (not list) — lazy evaluation."""
        p = StreamingCSVParser()
        gen = p.parse_file(sample_csv)
        # First row.
        first = next(gen)
        assert first["name"] == "Alice"
        # Continue to next.
        second = next(gen)
        assert second["name"] == "Bob"


class TestStreamingJSONParserInit:
    def test_init(self) -> None:
        p = StreamingJSONParser()
        assert p._decoder is not None


class TestStreamingJSONParserFile:
    def test_missing_file(self, tmp_path: Path) -> None:
        p = StreamingJSONParser()
        with pytest.raises(FileNotFoundError):
            list(p.parse_file(tmp_path / "missing.json"))

    def test_basic_parse(self, sample_json: Path) -> None:
        p = StreamingJSONParser()
        records = list(p.parse_file(sample_json))
        assert len(records) == 3
        assert records[0].data == {"id": 1, "name": "Alice", "tags": ["admin", "user"]}
        assert records[0].row_number == 1
        assert records[2]["name"] == "Charlie"

    def test_max_rows(self, sample_json: Path) -> None:
        p = StreamingJSONParser()
        records = list(p.parse_file(sample_json, max_rows=2))
        assert len(records) == 2

    def test_nested_array_unwrapped(self, tmp_path: Path) -> None:
        """If top-level is single array, unwrap and yield each item."""
        p = tmp_path / "nested.json"
        p.write_text(
            json.dumps([{"a": 1}, {"a": 2}, {"a": 3}]),
            encoding="utf-8",
        )
        records = list(StreamingJSONParser().parse_file(p))
        assert len(records) == 3
        assert records[0].data == {"a": 1}

    def test_chunked_parsing(self, tmp_path: Path) -> None:
        """Verify chunked parsing works for large JSON."""
        p = tmp_path / "large.json"
        data = [{"id": i, "value": f"item-{i}"} for i in range(1000)]
        p.write_text(json.dumps(data), encoding="utf-8")
        records = list(StreamingJSONParser().parse_file(p, chunk_size=64))
        assert len(records) == 1000
        assert records[999].data == {"id": 999, "value": "item-999"}

    def test_skips_non_dict_items(self, tmp_path: Path) -> None:
        p = tmp_path / "mixed.json"
        p.write_text(
            json.dumps([{"a": 1}, "string", 42, {"b": 2}]),
            encoding="utf-8",
        )
        records = list(StreamingJSONParser().parse_file(p))
        # Only dicts.
        assert len(records) == 2
        assert records[0].data == {"a": 1}
        assert records[1].data == {"b": 2}

    def test_iterator_lazy(self, sample_json: Path) -> None:
        p = StreamingJSONParser()
        gen = p.parse_file(sample_json)
        first = next(gen)
        assert first["name"] == "Alice"


class TestStreamingMemoryBehavior:
    """Test that large files don't load entirely into memory."""

    def test_large_csv_does_not_load_all(self, tmp_path: Path) -> None:
        """5000-row CSV — iterator-based, constant memory."""
        p = tmp_path / "big.csv"
        with open(p, "w", encoding="utf-8") as f:
            f.write("id,name\n")
            for i in range(5000):
                f.write(f"{i},row-{i}\n")
        parser = StreamingCSVParser()
        gen = parser.parse_file(p, chunk_size=512)
        # Pull first 100, then bail.
        for _ in range(100):
            next(gen)
        # Iterator still works (no exhaustion).
        assert next(gen) is not None

    def test_large_json_does_not_load_all(self, tmp_path: Path) -> None:
        """Large JSON array — chunked reading."""
        p = tmp_path / "big.json"
        data = [{"id": i} for i in range(2000)]
        p.write_text(json.dumps(data), encoding="utf-8")
        parser = StreamingJSONParser()
        gen = parser.parse_file(p, chunk_size=128)
        # Pull first 50.
        for _ in range(50):
            next(gen)
        # No exhaustion.
        assert next(gen)["id"] == 50


class TestSingleton:
    def test_csv_singleton(self) -> None:
        p1 = get_csv_parser()
        p2 = get_csv_parser()
        assert p1 is p2

    def test_json_singleton(self) -> None:
        p1 = get_json_parser()
        p2 = get_json_parser()
        assert p1 is p2

    def test_reset(self) -> None:
        p1 = get_csv_parser()
        reset_parsers()
        p2 = get_csv_parser()
        assert p1 is not p2


class TestExports:
    def test_module_all(self) -> None:
        from src.backend.core import streaming_parser

        assert len(streaming_parser.__all__) == 5


class TestRealisticExample:
    """Realistic: large file processing pipeline."""

    def test_etl_pipeline_csv(self, tmp_path: Path) -> None:
        """Simulate ETL: read 1000-row CSV, aggregate by name length."""
        p = tmp_path / "orders.csv"
        with open(p, "w", encoding="utf-8") as f:
            f.write("order_id,customer,amount\n")
            for i in range(1000):
                f.write(f"{i},customer-{i % 10},{i * 1.5}\n")
        parser = StreamingCSVParser()
        total = 0.0
        count = 0
        for record in parser.parse_file(p, max_rows=1000):
            total += float(record["amount"])
            count += 1
        # Sum 0..999 of i*1.5 = 1.5 * 999*1000/2 = 749250.0.
        assert count == 1000
        assert abs(total - 749250.0) < 0.01

    def test_etl_pipeline_json(self, tmp_path: Path) -> None:
        """Simulate ETL: read JSON, filter + transform."""
        p = tmp_path / "events.json"
        data = [
            {"id": i, "type": "user" if i % 2 == 0 else "system", "value": i}
            for i in range(500)
        ]
        p.write_text(json.dumps(data), encoding="utf-8")
        parser = StreamingJSONParser()

        # Filter user events only, compute total value.
        user_total = 0
        user_count = 0
        for record in parser.parse_file(p):
            if record["type"] == "user":
                user_total += record["value"]
                user_count += 1
        # Even numbers from 0..498: count=250, sum = 0+2+...+498 = 250*249 = 62250.
        assert user_count == 250
        assert user_total == 250 * 249  # 0+2+...+498 (no wait, last is 498)


class TestStreamingCSVGzip:
    """Sprint 175+ P1.4: gzip auto-detection для CSV."""

    def test_gzip_csv_detected_by_extension(
        self, tmp_path: Path
    ) -> None:
        """CSV.gz files auto-detected and decompressed on-the-fly."""
        import gzip

        csv_path = tmp_path / "data.csv"
        gz_path = tmp_path / "data.csv.gz"

        # Write plain CSV.
        csv_path.write_text("id,name\n1,Alice\n2,Bob\n", encoding="utf-8")

        # Create .gz version.
        with gzip.open(gz_path, "wt", encoding="utf-8") as f:
            f.write("id,name\n1,Alice\n2,Bob\n3,Charlie\n")

        parser = StreamingCSVParser()
        records = list(parser.parse_file(gz_path))
        assert len(records) == 3
        assert records[0]["name"] == "Alice"
        assert records[2]["name"] == "Charlie"

    def test_plain_csv_works(self, tmp_path: Path) -> None:
        """Plain CSV (no .gz) still works."""
        csv_path = tmp_path / "data.csv"
        csv_path.write_text(
            "id,name\n1,Alice\n2,Bob\n", encoding="utf-8"
        )
        parser = StreamingCSVParser()
        records = list(parser.parse_file(csv_path))
        assert len(records) == 2

    def test_gzip_with_max_rows(
        self, tmp_path: Path
    ) -> None:
        import gzip

        gz_path = tmp_path / "data.csv.gz"
        with gzip.open(gz_path, "wt", encoding="utf-8") as f:
            for i in range(100):
                f.write(f"{i},row{i}\n")
        parser = StreamingCSVParser()
        records = list(parser.parse_file(gz_path, max_rows=10))
        assert len(records) == 10

    def test_gzip_missing_file(self, tmp_path: Path) -> None:
        parser = StreamingCSVParser()
        with pytest.raises(FileNotFoundError):
            list(parser.parse_file(tmp_path / "missing.csv.gz"))
