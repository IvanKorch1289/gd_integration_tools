import logging
from typing import Any, Callable

import orjson

from src.dsl.engine.context import ExecutionContext
from src.dsl.engine.exchange import Exchange, ExchangeStatus, Message
from src.dsl.engine.processors.base import BaseProcessor

_eip_logger = logging.getLogger("dsl.eip")
_camel_logger = logging.getLogger("dsl.camel")

__all__ = (
    "MessageTranslatorProcessor",
    "SplitterProcessor",
    "ClaimCheckProcessor",
    "NormalizerProcessor",
    "SortProcessor",
)


class MessageTranslatorProcessor(BaseProcessor):
    """Конвертация форматов: JSON↔XML, JSON↔CSV.

    Работает через подключаемые конвертеры. По умолчанию
    поддерживает json→xml, xml→json, dict→csv, csv→dict.
    """

    def __init__(
        self, from_format: str, to_format: str, *, name: str | None = None
    ) -> None:
        super().__init__(name=name or f"translate:{from_format}→{to_format}")
        self._from = from_format
        self._to = to_format

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        body = exchange.in_message.body
        converted = self._convert(body)
        exchange.set_out(body=converted, headers=dict(exchange.in_message.headers))

    def _convert(self, body: Any) -> Any:
        key = f"{self._from}→{self._to}"

        if key in ("json→xml", "dict→xml"):
            return self._dict_to_xml(body if isinstance(body, dict) else {})

        if key in ("xml→json", "xml→dict"):
            return self._xml_to_dict(body if isinstance(body, str) else str(body))

        if key in ("dict→csv", "json→csv"):
            return self._dict_list_to_csv(body if isinstance(body, list) else [body])

        if key in ("csv→dict", "csv→json"):
            return self._csv_to_dict_list(body if isinstance(body, str) else str(body))

        return body

    @staticmethod
    def _dict_to_xml(data: dict, root_tag: str = "root") -> str:
        try:
            import xmltodict

            return xmltodict.unparse({root_tag: data}, pretty=True)
        except ImportError:
            parts = [f"<{root_tag}>"]
            for k, v in data.items():
                parts.append(f"  <{k}>{v}</{k}>")
            parts.append(f"</{root_tag}>")
            return "\n".join(parts)

    @staticmethod
    def _xml_to_dict(xml_str: str) -> dict[str, Any]:
        try:
            import xmltodict

            parsed = xmltodict.parse(xml_str)
            if len(parsed) == 1:
                return dict(next(iter(parsed.values())))
            return dict(parsed)
        except ImportError:
            import re as _re

            return {
                m.group(1): m.group(2)
                for m in _re.finditer(r"<(\w+)>([^<]*)</\1>", xml_str)
            }

    @staticmethod
    def _dict_list_to_csv(data: list[dict]) -> str:
        if not data:
            return ""
        try:
            import io

            import pandas as pd

            df = pd.DataFrame(data)
            return df.to_csv(index=False)
        except ImportError:
            headers = list(data[0].keys())
            lines = [",".join(headers)]
            for row in data:
                lines.append(",".join(str(row.get(h, "")) for h in headers))
            return "\n".join(lines)

    @staticmethod
    def _csv_to_dict_list(csv_str: str) -> list[dict[str, str]]:
        try:
            import io

            import pandas as pd

            df = pd.read_csv(io.StringIO(csv_str))
            return df.to_dict(orient="records")
        except ImportError:
            lines = csv_str.strip().split("\n")
            if len(lines) < 2:
                return []
            headers = [h.strip() for h in lines[0].split(",")]
            return [
                dict(zip(headers, [v.strip() for v in line.split(",")]))
                for line in lines[1:]
            ]


class SplitterProcessor(BaseProcessor):
    """Разбивает массив из body на отдельные Exchange.

    Каждый элемент обрабатывается sub-процессорами.
    Результаты собираются в ``split_results``.
    """

    def __init__(
        self,
        expression: str,
        processors: list[BaseProcessor],
        *,
        name: str | None = None,
    ) -> None:
        super().__init__(name=name or f"splitter:{expression[:20]}")
        self._expression = expression
        self._processors = processors

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        import jmespath

        body = exchange.in_message.body
        items = jmespath.search(self._expression, body)
        if not isinstance(items, list):
            exchange.set_property("split_results", [])
            return

        results: list[Any] = []
        for item in items:
            sub_exchange = Exchange(
                in_message=Message(body=item, headers=dict(exchange.in_message.headers))
            )
            sub_exchange.status = ExchangeStatus.processing

            for proc in self._processors:
                if sub_exchange.status == ExchangeStatus.failed or sub_exchange.stopped:
                    break
                await proc.process(sub_exchange, context)

            result = (
                sub_exchange.out_message.body
                if sub_exchange.out_message
                else sub_exchange.in_message.body
            )
            results.append(result)

        exchange.set_property("split_results", results)
        exchange.set_out(body=results, headers=dict(exchange.in_message.headers))


class ClaimCheckProcessor(BaseProcessor):
    """Camel Claim Check EIP — store payload, pass token through pipeline.

    mode="store": saves body to Redis, replaces with claim token.
    mode="retrieve": loads body from Redis using the token.
    """

    def __init__(
        self,
        *,
        mode: str = "store",
        store: str = "redis",
        ttl_seconds: int = 3600,
        name: str | None = None,
    ) -> None:
        super().__init__(name=name or f"claim_check:{mode}")
        self._mode = mode
        self._store = store
        self._ttl = ttl_seconds

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        import uuid

        if self._mode == "store":
            token = f"claim:{uuid.uuid4()}"
            body_bytes = orjson.dumps(exchange.in_message.body, default=str)
            try:
                from src.infrastructure.clients.storage.redis import redis_client

                await redis_client.set_if_not_exists(
                    key=token, value=body_bytes.decode(), ttl=self._ttl
                )
            except (ConnectionError, TimeoutError, OSError) as exc:
                _camel_logger.warning("Claim check store failed: %s", exc)
                return

            exchange.set_property("_claim_token", token)
            exchange.set_out(
                body={"_claim_token": token}, headers=dict(exchange.in_message.headers)
            )

        elif self._mode == "retrieve":
            token = exchange.properties.get("_claim_token")
            if not token:
                body = exchange.in_message.body
                if isinstance(body, dict):
                    token = body.get("_claim_token")

            if not token:
                exchange.fail("No claim token found")
                return

            try:
                from src.infrastructure.clients.storage.redis import redis_client

                raw = await redis_client.get(token)
                if raw is None:
                    exchange.fail(f"Claim token expired or not found: {token}")
                    return
                restored = orjson.loads(raw)
                exchange.set_out(
                    body=restored, headers=dict(exchange.in_message.headers)
                )
            except (ConnectionError, TimeoutError, OSError) as exc:
                exchange.fail(f"Claim check retrieve failed: {exc}")


class NormalizerProcessor(BaseProcessor):
    """Camel Normalizer EIP — auto-detect input format and normalize to canonical dict.

    Detects XML, CSV, YAML, JSON string and converts to dict,
    then optionally validates against a Pydantic schema.
    """

    def __init__(
        self, target_schema: type | None = None, *, name: str | None = None
    ) -> None:
        super().__init__(name=name or "normalizer")
        self._schema = target_schema

    @staticmethod
    def _detect_and_parse(body: Any) -> Any:
        if isinstance(body, dict):
            return body
        if isinstance(body, list):
            return body
        if not isinstance(body, str):
            return body

        text = body.strip()

        if text.startswith("<"):
            try:
                import xmltodict

                parsed = xmltodict.parse(text)
                if len(parsed) == 1:
                    return dict(next(iter(parsed.values())))
                return dict(parsed)
            except Exception:
                pass

        if text.startswith("{") or text.startswith("["):
            try:
                return orjson.loads(text)
            except Exception:
                pass

        try:
            import yaml

            result = yaml.safe_load(text)
            if isinstance(result, (dict, list)):
                return result
        except Exception:
            pass

        lines = text.split("\n")
        if len(lines) >= 2 and "," in lines[0]:
            headers = [h.strip() for h in lines[0].split(",")]
            return [
                dict(zip(headers, [v.strip() for v in line.split(",")]))
                for line in lines[1:]
                if line.strip()
            ]

        return body

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        body = exchange.in_message.body
        normalized = self._detect_and_parse(body)

        if self._schema is not None:
            try:
                validated = self._schema.model_validate(normalized)
                exchange.set_property("normalized_model", validated)
                normalized = validated.model_dump()
            except Exception as exc:
                exchange.fail(f"Normalization validation failed: {exc}")
                return

        exchange.set_out(body=normalized, headers=dict(exchange.in_message.headers))


class SortProcessor(BaseProcessor):
    """Camel Sort EIP — sort list body by key function.

    Sorts the exchange body (must be a list) by the given key
    expression. Supports ascending and descending order.

    Usage::

        .sort(key_fn=lambda item: item["created_at"], reverse=True)
        .sort(key_field="price")
    """

    def __init__(
        self,
        *,
        key_fn: Callable[[Any], Any] | None = None,
        key_field: str | None = None,
        reverse: bool = False,
        name: str | None = None,
    ) -> None:
        super().__init__(name=name or f"sort({'desc' if reverse else 'asc'})")
        self._key_fn = key_fn
        self._key_field = key_field
        self._reverse = reverse

    async def process(self, exchange: Exchange[Any], context: ExecutionContext) -> None:
        body = exchange.in_message.body
        if not isinstance(body, list):
            return

        if self._key_fn is not None:
            sorted_body = sorted(body, key=self._key_fn, reverse=self._reverse)
        elif self._key_field is not None:
            sorted_body = sorted(
                body,
                key=lambda item: (
                    item.get(self._key_field, 0) if isinstance(item, dict) else 0
                ),
                reverse=self._reverse,
            )
        else:
            sorted_body = sorted(body, reverse=self._reverse)

        exchange.set_out(body=sorted_body, headers=dict(exchange.in_message.headers))
