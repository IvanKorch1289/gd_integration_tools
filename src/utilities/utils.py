from base64 import b64decode, b64encode
from binascii import Error as BinasciiError
from datetime import datetime
from typing import Any, Type
from uuid import UUID

from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from app.core.decorators.singleton import singleton
from app.infrastructure.external_apis.logging_service import app_logger
from app.utilities.json_codec import from_jsonable, to_jsonable

__all__ = ("utilities", "AsyncChunkIterator")


@singleton
class Utilities:
    logger = app_logger

    def transfer_model_to_schema(
        self, instance: Any, schema: Type[BaseModel], from_attributes: bool = False
    ) -> BaseModel:
        try:
            return schema.model_validate(instance, from_attributes=from_attributes)
        except Exception as exc:
            self.logger.error(
                "Ошибка преобразования модели в схему: %s", str(exc), exc_info=True
            )
            raise ValueError("Ошибка преобразования модели в схему") from exc

    def _encode_base64_sync(self, data: Any) -> Any:
        if isinstance(data, bytes):
            return b64encode(data).decode("ascii")

        if isinstance(data, str):
            return b64encode(data.encode("utf-8")).decode("ascii")

        if isinstance(data, dict):
            return {key: self._encode_base64_sync(value) for key, value in data.items()}

        if isinstance(data, list):
            return [self._encode_base64_sync(item) for item in data]

        if isinstance(data, tuple):
            return tuple(self._encode_base64_sync(item) for item in data)

        return data

    async def encode_base64(self, data: Any) -> Any:
        return self._encode_base64_sync(data)

    def _decode_base64_sync(self, data: Any) -> Any:
        if isinstance(data, str):
            try:
                decoded_bytes = b64decode(data, validate=True)
                try:
                    return decoded_bytes.decode("utf-8")
                except UnicodeDecodeError:
                    return decoded_bytes
            except (BinasciiError, ValueError):
                return data

        if isinstance(data, dict):
            return {key: self._decode_base64_sync(value) for key, value in data.items()}

        if isinstance(data, list):
            return [self._decode_base64_sync(item) for item in data]

        if isinstance(data, tuple):
            return tuple(self._decode_base64_sync(item) for item in data)

        return data

    async def decode_base64(self, data: Any) -> Any:
        return self._decode_base64_sync(data)

    def _decode_bytes_sync(self, data: Any) -> Any:
        if isinstance(data, bytes):
            return data.decode("utf-8")

        if isinstance(data, dict):
            return {
                self._decode_bytes_sync(key): self._decode_bytes_sync(value)
                for key, value in data.items()
            }

        if isinstance(data, list):
            return [self._decode_bytes_sync(item) for item in data]

        if isinstance(data, tuple):
            return tuple(self._decode_bytes_sync(item) for item in data)

        return data

    async def decode_bytes(self, data: Any) -> Any:
        return self._decode_bytes_sync(data)

    def ensure_url_protocol(self, url: str) -> str:
        if not url.startswith(("http://", "https://")):
            return f"http://{url}"
        return url

    def generate_link_page(self, url: str, description: str) -> HTMLResponse:
        safe_url = self.ensure_url_protocol(url)
        return HTMLResponse(
            f"""
            <html>
                <body>
                    <p>{description} link:
                        <a href="{safe_url}" target="_blank">{safe_url}</a>
                    </p>
                </body>
            </html>
            """
        )

    def convert_numpy_types(self, value: Any) -> Any:
        import pandas as pd

        if pd.api.types.is_integer(value):
            return int(value)
        if pd.api.types.is_float(value):
            return float(value)
        if pd.api.types.is_bool(value):
            return bool(value)
        return value

    def convert_data(self, obj: Any) -> Any:
        return to_jsonable(obj)

    @staticmethod
    def convert_pattern(pattern: str) -> str:
        started_symbol = "^" if pattern == "/" else "^.*"
        return f"{started_symbol}{pattern.replace('*', '.*')}$"

    def custom_json_encoder(self, obj: Any) -> Any:
        if isinstance(obj, UUID):
            return {"__uuid__": True, "value": str(obj)}

        if isinstance(obj, datetime):
            return {"__datetime__": True, "value": obj.isoformat()}

        if isinstance(obj, BaseModel):
            return obj.model_dump(mode="python")

        raise TypeError(f"Неподдерживаемый тип: {type(obj)}")

    def custom_json_decoder(self, dct: dict[str, Any]) -> Any:
        if "__uuid__" in dct:
            return UUID(dct["value"])
        if "__datetime__" in dct:
            return datetime.fromisoformat(dct["value"])
        return dct

    def restore_data(self, obj: Any) -> Any:
        return from_jsonable(obj)

    async def safe_get(
        self, data: dict[str, Any], keys: str, default: Any = None
    ) -> Any:
        current: Any = data
        for key in keys.split("."):
            if not isinstance(current, dict):
                return default
            if key not in current:
                return default
            current = current[key]

        return current if current is not None else default


class AsyncChunkIterator:
    def __init__(self, chunks: list[bytes]):
        self.chunks = chunks
        self.index = 0

    def __aiter__(self) -> "AsyncChunkIterator":
        return self

    async def __anext__(self) -> bytes:
        try:
            chunk = self.chunks[self.index]
        except IndexError as exc:
            raise StopAsyncIteration from exc

        self.index += 1
        return chunk


utilities = Utilities()
