"""Universal Type Converters — Camel TypeConverter pattern.

Strategy-based conversion between formats. Each format pair is a ConversionStrategy.
Adding a new format = 1 class + 1 line in the registry.

Supported: JSON, YAML, XML, CSV, MessagePack, Parquet, HTML→JSON, BSON.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

import orjson

from src.backend.core.logging import get_logger
from src.backend.dsl.engine.context import ExecutionContext
from src.backend.dsl.engine.exchange import Exchange
from src.backend.dsl.engine.processors.base import BaseProcessor

__all__ = ("ConvertProcessor",)
_conv_logger = get_logger("dsl.converters")


class ConversionStrategy(ABC):
    """Базовый класс для format conversion strategies (Strategy pattern)."""

    @abstractmethod
    def convert(self, data: Any) -> Any:
        """Выполнить операцию convert."""
        ...


class JsonToYaml(ConversionStrategy):
    """Конвертирует JSON → YAML с сохранением unicode."""

    def convert(self, data: Any) -> Any:
        """Выполнить операцию convert."""
        import yaml

        if isinstance(data, str):
            data = orjson.loads(data)
        return yaml.dump(data, default_flow_style=False, allow_unicode=True)


class YamlToJson(ConversionStrategy):
    """Конвертирует YAML → JSON через orjson."""

    def convert(self, data: Any) -> Any:
        """Выполнить операцию convert."""
        import yaml

        if isinstance(data, str):
            data = yaml.safe_load(data)
        return data


class JsonToMsgpack(ConversionStrategy):
    """Сериализует JSON → MessagePack binary (use_bin_type=True)."""

    def convert(self, data: Any) -> Any:
        """Выполнить операцию convert."""
        import msgpack

        if isinstance(data, str):
            data = orjson.loads(data)
        return msgpack.packb(data, use_bin_type=True)


class MsgpackToJson(ConversionStrategy):
    """Десериализует MessagePack → Python object (raw=False для str keys)."""

    def convert(self, data: Any) -> Any:
        """Выполнить операцию convert."""
        import msgpack

        if isinstance(data, bytes):
            return msgpack.unpackb(data, raw=False)
        return data


class JsonToXml(ConversionStrategy):
    """Конвертирует JSON → XML через xmltodict (auto-wrap non-dict в root)."""

    def convert(self, data: Any) -> Any:
        """Выполнить операцию convert."""
        import xmltodict

        if isinstance(data, str):
            data = orjson.loads(data)
        if not isinstance(data, dict):
            data = {"root": data}
        return xmltodict.unparse(
            data
            if any((isinstance(v, dict) for v in data.values()))
            else {"root": data},
            pretty=True,
        )


class XmlToJson(ConversionStrategy):
    """Парсит XML → dict через xmltodict (auto-unwrap single-root)."""

    def convert(self, data: Any) -> Any:
        """Выполнить операцию convert."""
        import xmltodict

        if isinstance(data, str):
            parsed = xmltodict.parse(data)
            if len(parsed) == 1:
                return dict(next(iter(parsed.values())))
            return dict(parsed)
        return data


class CsvToParquet(ConversionStrategy):
    """Конвертирует CSV (string/list-of-dicts) → Parquet binary через polars."""

    def convert(self, data: Any) -> Any:
        """Выполнить операцию convert."""
        import io

        import polars as pl

        if isinstance(data, str):
            df = pl.read_csv(io.StringIO(data))
        elif isinstance(data, list) and data and isinstance(data[0], dict):
            df = pl.DataFrame(data)
        else:
            return data
        buf = io.BytesIO()
        df.write_parquet(buf)
        return buf.getvalue()


class ParquetToCsv(ConversionStrategy):
    """Конвертирует Parquet binary → CSV string через polars."""

    def convert(self, data: Any) -> Any:
        """Выполнить операцию convert."""
        import io

        import polars as pl

        if isinstance(data, bytes):
            df = pl.read_parquet(io.BytesIO(data))
            return df.write_csv()
        return data


class HtmlToJson(ConversionStrategy):
    """Извлекает структуру из HTML: title/headings/paragraphs/links/tables."""

    def convert(self, data: Any) -> Any:
        """Выполнить операцию convert."""
        if not isinstance(data, str):
            return data
        try:
            from selectolax.parser import HTMLParser

            tree = HTMLParser(data)
            return {
                "title": tree.css_first("title").text()
                if tree.css_first("title")
                else "",
                "headings": [h.text() for h in tree.css("h1, h2, h3")],
                "paragraphs": [p.text() for p in tree.css("p")],
                "links": [
                    {"text": a.text(), "href": a.attributes.get("href", "")}
                    for a in tree.css("a[href]")
                ],
                "tables": self._extract_tables(tree),
            }
        except ImportError:
            return {"raw_text": data[:10000]}

    @staticmethod
    def _extract_tables(tree: Any) -> list[list[list[str]]]:
        """Выполнить операцию  extract tables."""
        tables = []
        for table in tree.css("table"):
            rows = []
            for tr in table.css("tr"):
                cells = [td.text().strip() for td in tr.css("td, th")]
                if cells:
                    rows.append(cells)
            if rows:
                tables.append(rows)
        return tables


class JsonToBson(ConversionStrategy):
    """Сериализует dict → BSON binary (MongoDB storage format)."""

    def convert(self, data: Any) -> Any:
        """Выполнить операцию convert."""
        from bson import BSON

        if isinstance(data, str):
            data = orjson.loads(data)
        if isinstance(data, dict):
            return BSON.encode(data)
        return data


class BsonToJson(ConversionStrategy):
    """Десериализует BSON binary → Python dict."""

    def convert(self, data: Any) -> Any:
        """Выполнить операцию convert."""
        from bson import BSON

        if isinstance(data, bytes):
            return BSON(data).decode()
        return data


class DictToCsv(ConversionStrategy):
    """Сериализует list-of-dicts → CSV string через polars (fallback: manual join)."""

    def convert(self, data: Any) -> Any:
        """Выполнить операцию convert."""
        if not isinstance(data, list) or not data:
            return data
        try:
            import polars as pl

            df = pl.DataFrame(data)
            return df.write_csv()
        except ImportError:
            headers = list(data[0].keys())
            lines = [",".join(headers)]
            for row in data:
                lines.append(",".join((str(row.get(h, "")) for h in headers)))
            return "\n".join(lines)


class CsvToDict(ConversionStrategy):
    """Парсит CSV string → list-of-dicts через polars (fallback: manual split)."""

    def convert(self, data: Any) -> Any:
        """Выполнить операцию convert."""
        if not isinstance(data, str):
            return data
        try:
            import io

            import polars as pl

            df = pl.read_csv(io.StringIO(data))
            return df.to_dicts()
        except ImportError:
            lines = data.strip().split("\n")
            if len(lines) < 2:
                return []
            headers = [h.strip() for h in lines[0].split(",")]
            return [
                dict(zip(headers, [v.strip() for v in line.split(",")], strict=False))
                for line in lines[1:]
            ]


_STRATEGIES: dict[str, ConversionStrategy] = {
    "json→yaml": JsonToYaml(),
    "yaml→json": YamlToJson(),
    "json→msgpack": JsonToMsgpack(),
    "msgpack→json": MsgpackToJson(),
    "json→xml": JsonToXml(),
    "xml→json": XmlToJson(),
    "dict→xml": JsonToXml(),
    "xml→dict": XmlToJson(),
    "csv→parquet": CsvToParquet(),
    "parquet→csv": ParquetToCsv(),
    "html→json": HtmlToJson(),
    "json→bson": JsonToBson(),
    "bson→json": BsonToJson(),
    "dict→csv": DictToCsv(),
    "json→csv": DictToCsv(),
    "csv→dict": CsvToDict(),
    "csv→json": CsvToDict(),
    "dict→yaml": JsonToYaml(),
    "yaml→dict": YamlToJson(),
}


def register_conversion(
    from_fmt: str, to_fmt: str, strategy: ConversionStrategy
) -> None:
    """Зарегистрировать conversion."""
    _STRATEGIES[f"{from_fmt}→{to_fmt}"] = strategy


class ConvertProcessor(BaseProcessor):
    """Universal format converter — Camel TypeConverter pattern.

    Builder: .convert(from_format="yaml", to_format="json")
    """

    def __init__(
        self, from_format: str, to_format: str, *, name: str | None = None
    ) -> None:
        """Выполнить операцию   init  ."""
        super().__init__(name=name or f"convert:{from_format}→{to_format}")
        self._key = f"{from_format}→{to_format}"

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        """Обработать exchange согласно логике процессора. Читает body / properties, мутирует exchange, raises exceptions для error handling pipeline."""
        strategy = _STRATEGIES.get(self._key)
        if strategy is None:
            exchange.fail(f"No converter for {self._key}")
            return
        body = exchange.in_message.body
        try:
            converted = strategy.convert(body)
            exchange.set_out(body=converted, headers=dict(exchange.in_message.headers))
            exchange.set_property("convert_format", self._key)
        except ImportError as exc:
            exchange.fail(f"Converter dependency missing: {exc}")
        except (ValueError, TypeError) as exc:
            exchange.fail(f"Conversion {self._key} failed: {exc}")
